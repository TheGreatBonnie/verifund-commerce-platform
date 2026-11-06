# Single Shared A2A Endpoint for Seller Agents — Design

Date: 2026-11-06
Status: Design for approval. No code changes are made by this document.
Related docs:
- `docs/superpowers/specs/single-a2a-endpoint-multiple-seller-agents.md` (source recommendation; superseded where it contradicts this document)
- `docs/superpowers/specs/2026-11-06-verifund-multi-tenancy-design.md` (tenancy model, status axes, §12.2–§12.5 credential/registry/provisioning specs — binding)
- `docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md` (Neon target; see pointer note added 2026-11-06 — deferred, not binding for this milestone)
- `docs/superpowers/specs/2026-11-06-seller-agent-onboarding-design.md` (onboarding stub; consumes this design, does not restate it)
- `docs/superpowers/specs/seller-agent-config-seller-onboarding.md` (attached recommendation for onboarding configuration; **superseded** by Appendix B of this document)
- `docs/superpowers/specs/seller-agent-onboarding-recommendation.md` (source recommendation)
- `docs/superpowers/specs/verifund-multi-tenancy-recommendation.md` (original tenancy rationale)
- A2A Multi-Tenancy and Multi-Agent Routing guide: `https://a2a-protocol.org/latest/topics/multi-tenancy/`
- A2A Specification: `https://github.com/a2aproject/A2A/blob/main/docs/specification.md`

Related code: `apps/seller_agent`, `apps/buyer_agent`, `apps/registry`, `apps/verifund_control_plane`, `packages/commerce_core`, `packages/verifund_contracts`, `tests`.

---

## 1. Purpose

Verifund serves one A2A endpoint from which any number of logical Seller Agents
are reachable, instead of one deployed A2A server per seller. A buyer agent
selects an individual seller's agent at discovery time and reaches it through a
shared HTTPS endpoint; the shared runtime resolves, per request, which seller
and which organization the call is for, executes with that seller's configuration,
policies and data, and never crosses tenant boundaries.

This document records the decisions from the 2026-11-06 design grill
(Q1–Q32). It is deliberately explicit about **accepted risks** (§11) and about
what is **deferred** to the Neon milestone (§12). It does not authorize code
changes; implementation is tracked by a separate plan.

Scope cut made during the grill: **persistence is SQLite for now.** NeonDB
(PostgreSQL) is explicitly out of scope for this milestone and will be
re-decided then (§12).

## 2. Current state (as built)

Today there is no shared endpoint and no tenant routing:

- `docker-compose.yml` runs **four separate seller containers** — northwind
  (:9201), circuitforge (:9202), aurora (:9203), summit-tech (:9204) — each
  with its own YAML profile (`apps/seller_agent/seller_agent/profiles/*.yaml`),
  its own SQLite file (`data/<seller>.db`), its own static bearer token
  (`SELLER_*_TOKEN`), and its own `PUBLIC_BASE_URL`.
- `create_app()` in `apps/seller_agent/seller_agent/server.py` loads exactly
  one profile once at startup; `SellerService` holds one policy and one mandate
  in memory; `build_agent_card()` (`card.py`) emits one card advertising one
  `AgentInterface(url="{base_url}/a2a", …)` with no `tenant`.
- `BearerAuthMiddleware` checks one static `SELLER_TOKEN`; there is no
  caller-organization binding.
- The A2A `DatabaseTaskStore` is instantiated per process against the
  seller's own DB.
- Each profile embeds the seller's **entire catalog** (per-product floors,
  concession ladders, stock) plus its mandate — i.e., seller configuration and
  seller data are currently one file.
- `apps/registry` already stores per-seller and per-agent
  `card_url`/`card_json` with `organization_id`, `verified` (sellers) and
  `published` (agents) flags, and enforces the platform-issued `/{seller_id}/a2a`
  `card_url` rule (multi-tenancy design §12.3).
- The multi-tenancy design **anticipates but has not built** the shared A2A
  gateway: `POST /v1/agent-credentials/verify` (§12.2) is specified with the
  rule *"The A2A gateway rejects an envelope `tenant_id` that differs from the
  verified organization with `403`"*, and names the A2A gateway as the location
  of that enforcement.
- The pinned `a2a-python` SDK supports the routing primitives:
  `AgentInterface.tenant` and `SendMessageRequest.tenant` both exist
  (`tenant` is on the request envelope, not on `Message`).
- `langgraph-checkpoint-sqlite` (>=3.0,<4) is already a project dependency.

## 3. Target model

### 3.1 One shared runtime, many logical sellers

```
Buyer Agent (apps/buyer_agent)
  │  POST https://agents.verifund.com/{seller_id}/a2a
  │       Body: SendMessageRequest { tenant: "agent_northwind", … }
  ▼
Shared Seller Agent Runtime  (generalized apps/seller_agent, one deployment)
  1. Verify caller credential against control plane  /v1/agent-credentials/verify
     (30s positive cache, keyed on token hash; fail closed on outage)
  2. Read request.tenant (agent_id) → resolve agent → organization_id
     from the trusted directory in the shared sellers DB
     (envelope value is a routing hint, never proof of authorization)
  3. 404 unknown tenant · 401 bad credential · 403 URL↔tenant mismatch,
     org mismatch, or inactive recipient
  4. Load seller configuration from sellers.db (read fresh per request)
  5. Execute shared SellerExecutor/graph inside an org-bound scoped context
     (thread_id namespaced organization_id:{org}:{agent_id}:{thread})
  6. Persist order/offer/agreement/evidence rows scoped to organization_id
```

Unchanged from today: the LangGraph seller workflow, commerce policy engine,
catalog/inventory schema, A2A task model, settlement sandbox, and the registry's
discovery contract. What changes is **where the per-seller constants come
from**: one deployment-argument YAML becomes an `organization_id`-scoped
directory row.

### 3.2 A2A routing mechanisms used

The A2A multi-tenancy guide defines three complementary mechanisms. This design
uses **1 + 3**, with 2 as a defense layer:

| # | Mechanism | Use in Verifund |
|---|-----------|-----------------|
| 1 | URL/sub-path routing | `/{seller_id}/a2a` platform paths — satisfies the registry's `card_url` rule (§12.3); routing only |
| 2 | Auth-credential routing | Buyer credentials identify the **caller**, not the intended seller — defense layer, never the discriminator |
| 3 | `tenant` field routing | `AgentInterface.tenant = agent_<id>`; client echoes it per request; server cross-checks against the resolved agent (§12.2 rule) — the in-envelope integrity check |

### 3.3 `tenant` value semantics (Q3)

The `tenant` value is `agent_id` — the logical seller agent's identifier
(e.g. `agent_northwind`), an opaque routing string. It is **not**
`organization_id`: one organization may operate multiple agents (decision 7 in
the multi-tenancy design — revoking one agent never revokes the organization's
others). The runtime resolves `agent_id → organization_id` and uses the
organization as the data-isolation key.

### 3.4 One Agent Card per seller (Q4, Q9)

Discovery stays per-seller; buyers never see "the platform", they see sellers:

- Public card URL: `https://agents.verifund.com/{seller_id}/.well-known/agent-card.json`
  (or the registry serving its stored `card_json` for `card_url` — same projection).
- `supportedInterfaces[0].url` = `https://agents.verifund.com/{seller_id}/a2a`
- `supportedInterfaces[0].tenant` = `agent_<id>`
- Card content is generated on the fly from `seller_configs`
  (name, description, tagline, skills) — public fields only; never policies,
  floors, inventory, credentials, or internal IDs beyond `agent_id`.
- Registry remains the discovery surface; `card_url` stays platform-issued
  `/{seller_id}/a2a` (multi-tenancy design §12.3). Card publication happens at
  activation via the §12.4 control-plane → registry projection.

## 4. Request flow and denial semantics (Q22)

1. **Caller presents credential** (buyer-agent `vf_agent_*` token, or seeded
   demo credential bound to an organization per §12.2). Middleware extracts it;
   the static per-seller `SELLER_TOKEN` path is removed.
2. **Credential verification**: `POST /v1/agent-credentials/verify` →
   `{organization_id, agent_id, scopes, status}`. Only succeeds when the
   credential **and** the caller agent are `active`. Positive results are
   cached for at most **30 seconds**, keyed on token hash (§12.2). On control-plane
   error, **fail closed**: deny; never fall back to static tokens.
3. **Tenant resolution**: `request.tenant` is validated (known
   `agent_id` in the directory, `status == active`). Unknown → **404**
   A2A error (`AgentNotAvailableError`-style). Known but inactive, or
   `tenant` ↔ `{seller_id}` path ↔ registry org disagree with the verified
   caller/recipient binding → **403**. Invalid/expired credential →
   **401**. Mismatches are logged with both identities for abuse review.
4. **URL check**: `/{seller_id}/a2a` path must agree with the directory entry
   for `request.tenant`; disagreement → 403.
5. **Context build**: `SellerContext { agent_id, organization_id, policy,
   mandate, catalog handle, config_version }` constructed from `sellers.db`,
   fresh per request (§7.6). Repositories/stores in this context are
   **organization-bound** (§7.2).
6. **Execution**: shared SellerExecutor/graph; checkpoints via
   `AsyncSqliteSaver` (§7.5). Tool calls pass the config-declared allowlist and
   policy bounds (§8).
7. **Persistence**: orders/offers/agreement reviews/evidence/settlement tokens
   all written with `organization_id` (+ `agent_id` stamp where decided) — §7.3.
8. **Response**: A2A response; tasks recorded in `task_ownership` (§7.4).

## 5. Caller authentication and authorization (Q6, Q17, Q20)

- **Authentication**: control-plane `agent-credentials/verify` only. Static
  `SELLER_*_TOKEN` values are removed from runtime config; they exist solely
  as seeded demo credentials bound to their demo organizations (§12.2).
- **Cache**: 30s positive cache on credential verification (§12.2). The seller
  **configuration** is never cached (§7.6).
- **Authorization scope**: any active, verified caller may message any active
  seller (open-marketplace commerce). Authorization = "caller is a valid
  active agent" + the §12.2 403 rule. No per-pair ACLs in this milestone.
- **What `tenant` is not**: the envelope `tenant` never grants data access.
  Authorization derives only from the verified credential and the server-side
  registry/directory resolution.
- `seller_id` values remain globally unique and map 1:1 to an organization
  (§12.1); the directory enforces that uniqueness.

## 6. Tool authorization (Q10)

- Seller configuration declares its **tool allowlist** (catalog search, quote,
  negotiate, order, agreement review, evidence) and tool arguments are bounded
  by the seller's policy floors/ceilings (list price, floor, concession ladder,
  warranty window, returns days, etc.).
- The executor denies any tool not on the seller's allowlist before execution.
- "Unique integration" for a seller = a **registered adapter** referenced by
  config — never per-seller Python modules in the shared runtime.

## 7. Data topology — SQLite first

**Decision (grill rev. Q26):** one shared `sellers.db`,
`organization_id` on every seller-owned table, enforcement in the application
layer (SQLite has no RLS). Neon PostgreSQL is deferred (§12).

### 7.1 Databases

| Database | File | Contents |
|---|---|---|
| Seller shared | `data/sellers.db` | `seller_configs` (directory), `task_ownership`, catalog/inventory, offers, orders, seller_agreement_reviews, settlement_tokens, evidence_outbox |
| Checkpoints | `data/seller_checkpoints.sqlite` | LangGraph checkpoint state (dedicated; §7.5) |
| Existing | `data/verifund.db`, registry, control-plane DBs | unchanged |

WAL mode on `sellers.db`; single writer process; busy timeout set. Existing
per-seller `.db` files are **not** imported (Q32) and remain untouched.

### 7.2 Org-bound scoped store (fail closed) — Q30

- Repositories/stores are constructed **only** with a verified `organization_id`
  (and `agent_id` where stamped). Constructing without it raises; every query
  adds `WHERE organization_id = :org` centrally. There is no supported way to
  execute a seller-data query without an org context — the application-layer
  mirror of the control plane's §5.2 fail-closed rule (unset → zero rows).
- Raw engine/session access is confined to the Unit-of-Work and migration/seed
  paths; business code receives the scoped store only.
- `organization_id` is stored as the seller organization's UUID string
  (consistent with the tenancy design; `seller_id` text slug stays the public
  path key). `agent_id` is stamped on orders and evidence rows; A2A tasks
  carry it via `task_ownership` (§7.4) (Q13).
- Cross-tenant negative tests are part of the cutover gate (§10).

### 7.3 Shared-schema changes in `sellers.db`

- Add `organization_id TEXT NOT NULL` to: `inventory`, `offers`, `orders`,
  `seller_agreement_reviews`, `settlement_tokens`, `evidence_outbox` (and
  `seller_configs`). Add `agent_id TEXT NOT NULL` to `orders` and
  `evidence_outbox` (Q13); A2A task attribution lives in `task_ownership` (§7.4).
- New `products` table (Appendix B B.6): full SellerPolicy product model with
  optional-with-defaults columns; composite PK `(organization_id, sku)`;
  `organization_id` only (no `agent_id`) — one org's agents share the catalog.
  `inventory` PK becomes `(organization_id, sku)`.
- Add `organization_id` to all seller indexes; idempotency/unique constraints
  are **rescoped** to `(organization_id, …)` (e.g. order idempotency key).
- `seller_configs` (new): `agent_id` PK, `organization_id` NOT NULL,
  `seller_id` (unique text slug), display fields (`name`, `tagline`),
  `policy_json` (list/floor/initial prices, concession ladder, warranty,
  commerce terms), `mandate_json`, `tool_allowlist_json`, `status`
  (`active|disabled`), `policy_version`, `policy_hash`, `created_at`,
  `updated_at`. This is the hot-path read (§7.6) and the card projection source.
- `task_ownership` (new): `task_id` PK, `organization_id` NOT NULL,
  `agent_id` NOT NULL, `created_at`, `context_id`.
- Row-level migration is via one Alembic-style/schema migration in this
  milestone (SQLite DDL), applied to a fresh file (Q32 — no data import).

### 7.4 A2A task isolation — Q31

`DatabaseTaskStore` owns its library table and exposes no org column. Isolation
is enforced around it:

- On task creation, write `task_ownership(task_id, organization_id, agent_id)`.
- All task read/update paths (`tasks/get`, `tasks/list`, subscription setup,
  push handling) join/filter on `task_ownership` for the caller's org; listing
  never returns another org's tasks.
- Task IDs remain unguessable (library-generated UUIDs).
- Cross-tenant negative tests assert: org B cannot see/act on org A's task,
  including via list endpoints.

### 7.5 Checkpoints — Q14/Q27

- Durable checkpoints **now** (not MemorySaver), via `AsyncSqliteSaver` on a
  **dedicated** `seller_checkpoints.sqlite` (one connection; never the
  operational file).
- `thread_id` format: `organization_id:{organization_id}:{agent_id}:{thread_id}`
  — client-supplied ids cannot escape their namespace; the executor prefixes,
  it does not trust.
- Keeping checkpoints out of `sellers.db` preserves the scoped-store invariant
  with zero library surgery.

### 7.6 Seller configuration resolution

- `seller_configs` is read **fresh on every request** (no config cache — Q15).
  One indexed lookup by `agent_id`; the hot path is otherwise one verify
  (usually cached) + this select.
- The four YAML profiles (`northwind.yaml`, `circuitforge.yaml`, `aurora.yaml`,
  `summit-tech.yaml`) become **seed fixtures** loaded by the cutover seed
  script (Q32); they are not read at runtime.
- The control plane is the system of record for lifecycle/status/credentials
  and registry projection (§12.2–§12.4); the shared runtime does not read the
  control plane at request time (Q23). `status` in `seller_configs` is synced
  from activation/deactivation events and verified against credential status on
  the hot path.
- `policy_version`/`policy_hash` are stored for §12.5 drift detection; this
  milestone records them at seed and on policy writes, but the daily drift
  sweep is out of scope (§13).

### 7.7 Evidence outbox sweeper — Q25

- One in-process sweeper task; it iterates active sellers and posts pending
  `evidence_outbox` rows to the Verifund control plane as each seller
  (`VERIFUND_MODE` semantics unchanged), idempotent on
  `(organization_id, transaction_id)`.
- Cross-tenant iteration is application code, audited, and read-mostly; it is
  the single sanctioned exception to org-bound scoping, expressed as an
  explicit `UNSCOPED` code path with logging — never a silent default.

## 8. Agent Card details

Generated per request from `seller_configs` (or memoized by config row hash if
profiling demands it — an internal optimization, invisible to clients):

- `name`, `description`, `version`, `provider.organization` = seller display
  name; URL = `https://agents.verifund.com/{seller_id}/.well-known/agent-card.json`.
- `skills`: today's fixed commerce skill set.
- `supportedInterfaces[0]`: `url` = `https://agents.verifund.com/{seller_id}/a2a`,
  `protocol_binding` = existing binding (JSONRPC), `protocol_version` =
  `PROTOCOL_VERSION_CURRENT`, `tenant` = `agent_<id>`,
  `url` path segment `{seller_id}` must resolve to the same organization as
  `tenant` (enforced §3.2/§4).
- Registry `card_json` remains the public projection; buyer discovery unchanged.

## 9. Isolation invariants (non-negotiable)

1. The envelope `tenant`/`{seller_id}` path are routing inputs only; access is
   granted solely from the verified credential + server-side resolution.
2. No seller-data query executes without a verified `organization_id`
   (org-bound scoped store); unset context fails closed.
3. `thread_id`/`context_id` are namespaced `organization_id:{org}:{agent_id}:{id}`
   at the executor boundary; client values are never used raw.
4. Configuration reads are never cached across requests (only credential
   verification caches, 30s max, keyed on token hash).
5. `task_ownership` is the gate for every task read/update/list; no path
   bypasses it.
6. Cross-tenant negative tests (seller A invisible to buyer/seller B across
   orders, tasks, evidence, cards) gate every cutover (§10).
7. The `UNSCOPED` sweeper path is explicit, audited, and unreachable for
   ordinary requests.
8. Card content contains no policy bodies, floors, inventory, or credentials.
9. Agent status is re-read via credential verification; a revoked agent stops
   working within the 30s credential cache window (Invariant inherited from §12.2).
10. Mismatch/abuse signals (URL↔tenant disagreement, verify-vs-directory
    mismatch) are logged with both identities for review.

## 10. Rollout — big bang, full gate — Q11, Q12, Q24

**Chosen strategy:** single big-bang cutover to the shared runtime for all
four demo sellers; **no rollback parachute is kept** (accepted — §11). Old
per-seller container definitions remain in git history only.

**Mandatory pre-cutover gate** (all must pass before flipping registry
`card_url`s):

1. Existing seller-agent and registry unit/integration tests pass against the
   shared runtime (`sellers.db` fixtures).
2. The four-seller demo negotiation flow (browse → offer → counter → order →
   evidence/settlement in sandbox) passes **per seller**: northwind,
   circuitforge, aurora, summit-tech.
3. Cross-tenant negative tests pass: task listing/get/update isolation,
   order/evidence invisibility, config isolation, card projection isolation,
   wrong-credential → 401, org/tenant mismatch → 403, unknown → 404.
4. Seeded cards in the registry match generated cards (`card_hash` equality).
5. Evidence outbox sweeper verified end-to-end for one seller per org shape.

**Cutover sequence:** merge → build image → fresh `sellers.db` seed from YAML
fixtures + control-plane org/agent/credential registration → run gate → flip
registry `card_url`/`published` for the four sellers in one step → smoke the
demo → retire the per-seller container definitions.

## 11. Accepted risks (explicit)

| Risk | Decision | Consequence |
|---|---|---|
| No rollback path (Q12) | Accepted | A bad cutover is fixed forward (hotfix) or by re-deploying old images **manually from git history**; nothing in infra guarantees availability during a bad release |
| No per-tenant fairness/concurrency limits (Q21) | Accepted | One noisy seller can starve the shared process; mitigated only by existing per-request timeouts |
| Single file for all seller data (Q26) | Accepted | Corruption/lock contention blast radius = all sellers; WAL + single writer + backup discipline mitigate |
| No config cache (Q15) | Accepted | Extra indexed SELECT per request; p99 latency rises; trading freshness for simplicity |
| Credential 30s cache (Q17) | Kept | Revocation takes up to ~30s to take effect (same as §12.2) |
| Big-bang cutover (Q11) | Accepted | No incremental production learning; all-or-nothing demo failure mode |
| Durable checkpoints shared file without RLS (Q27/§7.5) | Accepted | Isolation depends on thread namespacing + executor discipline; checkpoint contents are brokered by application code only |

## 12. Neon PostgreSQL — deferred (Q16, Q29)

**This milestone implements SQLite.** The Neon Postgres design remains a
target, not a constraint. A pointer note to this effect has been added to
`docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md`
(2026-11-06).

The Neon milestone must re-decide, with real infra in hand:

- Per-seller databases vs one shared database with enforced RLS (Q7's original
  PostgreSQL answer was shared DB + RLS; the SQLite milestone ships shared DB +
  application scoping).
- Checkpoint tables: dedicated schema/DB without RLS per the §5.5/§5.6
  exception pattern, or first-class RLS.
- Migration runner and role model for seller schema (supersedes §8's
  "Seller migrations run once per seller database" if shared DB is chosen).
- Connection pooling per bounded context, WAL/vacuum equivalents, backup/PITR.

Until then, the Neon document's §5 (RLS) and §7.3/§8 seller-isolation language
are **not binding** for the seller runtime; the isolation mechanisms are §7 and
§9 of this document.

## 13. Non-goals

- Neon/PostgreSQL migration, RLS, or role engineering (deferred to Neon milestone).
- Seller onboarding wizard UX beyond this milestone's configuration steps and
  the catalog-import slice (B.4/B.6); policy editor UX (stub spec owns it).
  External commerce integrations (OAuth/provider APIs, live catalog sync).
- Per-pair buyer↔seller ACLs (Q20).
- Per-tenant quotas, billing, rate limiting (Q21).
- Daily policy-drift sweep and console surfacing (§12.5) — schema and hashes
  exist; the sweeper is deferred.
- Dedicated/enterprise seller tier (Q1 — fully shared runtime; a future tier
  would be a new spec).
- Importing historical orders/agreements from the four legacy seller DBs (Q32).
- Registry/control-plane schema changes beyond §12.2–§12.4 as specified.

## 14. Open questions for the implementation plan

- Exact `CREATE TABLE` DDL and SQLite migration runner choice.
- Test fixture strategy for `sellers.db` (per-test temp file vs reset of shared
  seeded DB) — must preserve cross-tenant negative tests' fidelity.
- Sweeper cadence and backpressure (fixed interval vs evidence arrival).
- Card memoization key (raw row vs policy_hash) if card generation profiles hot.
- Whether `seller_configs` lives forever as designed or splits into registry mirror later.

## 15. Decision log (grill, 2026-11-06)

| # | Decision | Choice |
|---|---|---|
| Q1 | Deployment model | **Fully shared runtime** (not hybrid) |
| Q2 | Routing mechanism | **URL path + `tenant` field**; auth as defense layer |
| Q3 | `tenant` value | **`agent_id`**; org is the isolation key |
| Q4 | Card strategy | **One Agent Card per seller** |
| Q5 | Resolver location | **Generalize `seller_agent`** (no external proxy) |
| Q6 | Caller auth | **Control-plane `agent-credentials/verify`** (§12.2) |
| Q7 | State isolation | **Shared DB** (initially PG+RLS; revised by SQLite directive → Q26) |
| Q8 | Config source | **DB-backed, seeded from YAML** |
| Q9 | Card hosting | **Platform paths** `/{seller_id}/.well-known/…` |
| Q10 | Tool authz | **Config-declared allowlist** + policy bounds |
| Q11 | Rollout | **Big-bang cutover** |
| Q12 | Rollback | **No parachute** (accepted) |
| Q13 | Isolation key | **`organization_id` + `agent_id` audit stamp** |
| Q14 | Checkpoints | **Durable checkpoints now** |
| Q15 | Config cache | **No cache — read per request** |
| Q16 | Deliverable | **New dated design doc + Neon pointer note** |
| Q17 | Credential cache | **Keep 30s** |
| Q18 | Checkpoint isolation | **Dedicated schema/db, no RLS; namespaced thread_id** |
| Q19 | Enforcement shape | **Control-plane pattern mirrored** (adapted to app-level on SQLite) |
| Q20 | Caller scope | **Any active verified caller → any active seller** |
| Q21 | Fairness limits | **None** (accepted) |
| Q22 | Denial semantics | **404 unknown · 401 bad credential · 403 mismatch/inactive** |
| Q23 | Config read path | **Seller DB for config; control plane for creds only** |
| Q24 | Cutover gate | **Full gate before flip** (§10) |
| Q25 | Evidence outbox | **Single cross-org sweeper** |
| Q26 | SQLite topology | **One shared `sellers.db` + app scoping** |
| Q27 | Checkpoint store | **Dedicated shared `seller_checkpoints.sqlite`** |
| Q29 | Neon handling | **Pointer note, doc left intact** |
| Q30 | Scoping mechanism | **Org-bound scoped store, fail closed** |
| Q31 | A2A tasks | **Sidecar `task_ownership` + org-filtered reads** |
| Q32 | Seeding | **Fresh seed from YAML fixtures; legacy `.db` files not imported** |

---

## Appendix B. Seller onboarding — agent configuration (2026-11-06 onboarding grill)

B.1 **Purpose.** How a seller configures its A2A Seller Agent inside the seller
workspace UI after Clerk authentication, and what the backend must do to make
that real. This appendix supersedes
`docs/superpowers/specs/seller-agent-config-seller-onboarding.md`
(recommendation prose) where they differ; the decisions here were settled in
the 2026-11-06 onboarding grill (O1–O27, after the catalog-import amendments).
Related: the console, control plane and seller runtime code paths listed in §2
and §7.

B.2 **As-built today.** Console `(seller-onboarding)/seller/onboarding/[step]/page.tsx`
is a placeholder for every step; `apps/console/lib/onboarding.ts` defines the
seven steps `profile → verification → integrations → agent_setup → policies →
testing → activation` (`sellerEntryPath` routes verified sellers elsewhere).
FastAPI control plane exposes `require_identity`, onboarding create/read +
verification submit, and agent routes for **test / issues / verify** only;
`provision_agent`, `confirm_policy`, `activate_agent` exist in
`agents/lifecycle.py` but are **not routed** and two of them still carry
placeholders (`policy_hash="0"*64`, six hardcoded test checks of `True`).

B.3 **Human vs machine identity.** Clerk authenticates the human
administrator only; every console→control-plane call is pinned to one Verifund
organization by `require_identity` (Clerk session token verified against the
Clerk backend API, `azp` allowlisted; `tenant_id` = Verifund organization id
resolved from `clerk_org_id`; never taken from the request body). The Seller
Agent is a machine identity: opaque `vf_agent_*` credential, hashed at rest,
issued per agent, verified by `POST /v1/agent-credentials/verify` (§12.2 of
the tenancy design; 30s positive cache). The seller admin's Clerk session is
never a credential for the agent, and no secret ever reaches the browser.

B.4 **The configuration steps** — the four agent steps (`agent_setup`,
`policies`, `testing`, `activation`) plus a minimal `integrations` slice (B.6;
O2 as amended by O20). `profile` and `verification` remain stubs this
milestone. All edits require `org:agents:manage`; all edits are
compare-and-swap on `expected_config_version`; mismatch → `409` with the
latest config (O12).

| B.4.1 `agent_setup` | Creates the draft agent on first save: `agent_<slug>` unique per org (O3); display `name`, `description` (editable, `agent_id` immutable). Instructions = generated default template from the business profile + seller-editable free-text body (O7): sanitized (control chars stripped), length-capped (~4k chars), stored versioned in `seller_configs` with `config_version`; never on the public card. Capability checkboxes map 1:1 to the commerce skill set (`catalog.search`, `inventory.check`, `pricing.quote`, `offer.create`, `offer.negotiate`, `agreement.review`, `order.create`) and are persisted as the agent's **tool allowlist** (O4). **All boxes default ON (O14 — accepted divergence).** A read-only public card preview panel is shown for the seller to review (B.4.4) before activation (O13). |
| B.4.2 `policies` | Global autonomy caps only (O8): `max_discount_bps` (default 1000 = 10%), `autonomy_mode` (`read_only \| assisted \| policy_bounded`; default `policy_bounded`), and the three fixed human-escalation rules (below floor / above cap / non-standard terms) — always on. Per-product floors stay catalog data; not editable here. Policy body is authoritative in the seller runtime's config store; saving writes via the runtime and records `policy_version`/`policy_hash` in the control plane (§12.4–12.5 of the tenancy design) (O5). |
| B.4.3 `testing` | Real checks, not placeholders (O9): (1) agent credential verifies against the control plane; (2) catalog returns a known SKU for the org; (3) pricing bounds refuse out-of-range offers (floor and ceiling); (4) mediated A2A round trip returns a valid response; (5) an action above the agent's authority ceiling escalates; (6) a revoked credential stops passing. Runs against the sandbox profile (`VERIFUND_MODE=sandbox`). Each check is recorded in `agent_test_runs` with policy/card hashes; the wizard renders results and blocks `activation` until a run passes for the current hashes. |
| B.4.4 `activation` | Gates (O11): organization `verified` · no policy drift · a passing test run for the current `policy_hash`+`card_hash` · ≥1 active credential. On success the agent transitions to `active` and the registry projection publishes the card (`published=true`; unpublish on suspend, not delete). Card URL = `agents.verifund.com/{seller_id}/.well-known/agent-card.json` (§3.4); advertised `tenant` = `agent_<slug>`. The seller portal `/seller/agent` renders the **same** components/forms as the wizard for post-activation edit-in-place (O10); credential material is never shown — status metadata only (issued/active/revoked/last rotation); rotation deferred to post-activation hardening (O15). |

B.5 **Provisioning flow (synchronous, idempotent, saga) — O5, O6, O11, O16.**

Wizard "Finish setup" (`POST /v1/agents/{id}/provisions` — routed by B.4) executes
inline and returns the final agent status (refresh-safe; target seconds on the
demo topology):

1. `require_identity` → business organization; require `org:agents:manage`.
2. Idempotency key `(organization_id, Idempotency-Key: <client-generated-uuid>)`;
   a replay returns the recorded transition — never a second agent.
3. Control plane creates/updates the `draft` agent (`create_agent` state
   machine: `draft → configuring` on first save, `configuring → testing` when
   the test suite runs, `testing → active` on activation).
4. **Card + capability projection** computed by the runtime: card `skills` are
   **derived** from the tool allowlist — never edited independently (O4);
   advertised can never exceed authorized.
5. Policy/config write goes to the **shared seller runtime**, not the control
   plane (§12.4-3 "seller agent's store is authoritative"): CP calls
   `POST {seller_runtime}/internal/agent-configs` (service-credential auth,
   single-use scope); the runtime validates, computes canonical
   `policy_version`/`policy_hash` from the config payload, upserts
   `seller_configs`, and returns both hashes (O16).
6. Control plane records hashes on the agent row, recomputes `card_hash`, and
   at activation publishes the registry projection (`agents.published=true`,
   desired card_url/card_json) (§12.3–12.4 of the tenancy design).
7. Any step failure marks that step `failed` with an audit event; the seller
   retries from the failing step; no 2PC/saga framework — explicit per-step
   idempotent operations + compensation (unpublish card, revoke credential) on
   terminal failure.

B.6 **Catalog import from file via the onboarding UI** — supersedes O19.
Fresh organizations bring their own products: the `integrations` step gains a
minimal **"Import product catalog"** slice (O20; the rest of the step —
external e-commerce/ERP OAuth, live sync — stays a stub).

- **Surface (console):** in the integrations panel, the seller can (a) upload
  a `.json`/`.yaml`/`.yml` file, (b) paste the document inline, (c) click
  **Load example catalog** (bundled `example-catalog.json`/`.yaml`, subset of a
  demo profile — needed for the O17 walkthrough on otherwise-empty orgs), or
  (d) download an annotated **template**. No silent seeding ever occurs.
- **Format (O21):** JSON and YAML, dispatched on content sniff (never on the
  filename extension alone). Canonical import schema = one document `{version: 1,
  currency: "USD"?, products: [...]}`; products match the `SellerPolicy` product
  model.
- **Validation (O23):** strict, all-or-nothing. Required per product: `sku`,
  `name`, `list_unit_price_cents`, `initial_unit_price_cents`,
  `floor_unit_price_cents`, `category`, `stock_on_hand`. Invariants:
  `floor ≤ initial ≤ list` per SKU; no duplicate SKUs in the file; unknown
  fields rejected; per-product currency consistency when `currency` present;
  ≤ 2 MB and ≤ 1000 SKUs per onboarding import. Every violation aborts the
  import with a structured `{errors: [{row, field, message}…]}` report and
  **zero writes** (single transaction).
- **Storage (O22, O26): normalized tables.** New `products` table in
  `sellers.db`: composite PK `(organization_id, sku)`, `organization_id` only,
  full product model with optional-with-defaults columns (name, prices,
  category, stock, returns/delivery days, warranty months/addons, concession
  ladder JSON, description, image_emoji, color, rating, tag) so the runtime
  constructs a byte-equivalent `SellerPolicy` from DB rows. `inventory` PK
  becomes `(organization_id, sku)`; stock columns keep `on_hand` / `incoming`
  / `incoming_days`.
- **Import semantics:** re-import **upserts by SKU**; new SKUs are inserted,
  existing ones updated. A **full replace** (remove products absent from the
  file) requires an explicit `replace_catalog=true` flag from a second,
  confirmed UI action — never from a single click. Imported
  `stock_on_hand`/`incoming_stock` wins when present; otherwise existing
  inventory values are retained.
- **Write path (O24):** the control plane does **not** write `sellers.db`.
  CP endpoint `POST /v1/seller/catalog/import` (auth: `org:agents:manage`)
  forwards to the shared runtime: `POST {seller_runtime}/internal/catalog/import`
  (service credential, same pattern as B.5 step 5). The runtime parses,
  validates, upserts `products` + syncs `inventory` in one transaction, and
  returns `{inserted, updated, replaced, errors}`. Idempotent on the wizard's
  `Idempotency-Key`; replay returns the recorded result.
- **No catalog hash (O27):** the catalog is data, not behavioral authority.
  Catalog edits never trigger `policy_drift`, never invalidate a passing
  `agent_test_runs` row, and play no part in activation gates — B.4.3's
  checks re-read the current `products`/`inventory` rows live at call time.

B.7 **Milestone boundary (build scope) — O2(amended), O18, O20.** This
milestone delivers: the four agent steps (B.4) and the minimal integrations
catalog-import slice (B.6) with their control-plane endpoints
(`POST /v1/agents`, `PATCH …/config`, `PATCH …/policies`,
`POST …/test`, `POST …/activate`, `GET …/status`,
`POST /v1/seller/catalog/import`), the console screens and portal reuse
(O10), the `/internal/agent-configs` and `/internal/catalog/import` runtime
endpoints, the `seller_configs` read path in request handling, and
`products`/`inventory` provisioning — hot-path reads must construct the
`SellerPolicy` from `products` + `seller_configs`, never by parsing YAML per
request (flagged 2026-11-06) — a minimal shared-runtime slice
**layered on the single-endpoint design in this same document**. The cutover
(registry flip of the four demo sellers, container retirement) stays in
that milestone's §10; `profile`/`verification` UI steps and credential
rotation remain out of scope.

B.8 **Acceptance gate — O17, amended O25.** Fresh-org walkthrough in a clean
environment: Clerk signup → org creation → wizard → **import the example
catalog (one click)** → instructions override → capability toggles →
`policies` save → `testing` (real checks pass against imported data) →
`activation` (card published; registry discovery returns the agent) →
buyer-side A2A call resolves to exactly this organization and negotiates.
Plus: control-plane endpoint integration tests, saga idempotency/retry tests
(replay without duplicates; mid-saga failure resume), catalog-import tests
(file/paste/example; validation aborts with zero writes; upsert vs replace
semantics; org isolation on products/inventory), scoping-invariant tests
(cross-tenant negative tests per §9/B.4), and the existing suite green.

B.9 **Accepted risks / divergences.**
- **All capabilities default ON** at onboarding (O14) — deliberate
  divergence from least-privilege default; sellers trim power by unchecking.
  Success criterion for the demo outweighs defense-in-depth default here.
- **Synchronous provisioning blocks the UI** briefly (O6); async promotion is
  the documented escape hatch if steps outgrow the request budget.
- **Imported catalogs are only as good as the seller's file** — strict
  validation catches structural and pricing-invariant errors (floor/initial/list
  ordering, duplicates), never bad business data (wrong floors, stale stock).
  No starter fixture ever lands in an org silently; the seller always performs
  or confirms the import (O25).
- **All-or-nothing aborts** mean one bad row rejects the whole file; sellers
  must fix and re-upload rather than receive a half-imported catalog (O23).
- **Hardcoded `agent_test_runs` placeholders replaced by real checks** (O9) —
  this removes the previous silent pass-through; activation is blocked until
  real checks pass.

B.10 **Open/deferred items.** Credential rotation UX and endpoint (O15);
integrations beyond the catalog-import slice (external catalog sync via
OAuth/provider APIs, incremental updates); policy-drift daily sweep
(§12.5, unchanged); per-category autonomy caps (rejected O8); per-pair
buyer↔seller ACLs (Q20, Appendix A); async provisioning transport; portal
editing of granular `agent_policies`-style rows beyond autonomy caps;
full-replace UX confirmation polish.

B.11 **Decision log (onboarding grill, 2026-11-06).**

| # | Decision | Choice |
|---|----------|--------|
| O1 | Deliverable | **Decisions land in this document (Appendix B)**; the onboarding-config recommendation is marked superseded here |
| O2 | Build scope | **Four config steps + endpoints** (`agent_setup`, `policies`, `testing`, `activation`) + minimal integrations catalog-import slice (O20); `profile`/`verification` remain stubs |
| O3 | `agent_id` format | **`agent_<slug>` unique per org**; permanent, independent of display name |
| O4 | Skills vs tools | **Card skills derived from the tool allowlist; never edited independently**; advertised ⊆ authorized |
| O5 | Cross-store provisioning | **Idempotent inline saga, control plane orchestrates**; `(organization_id, Idempotency-Key)` replay-safe; no 2PC; compensating actions on terminal failure |
| O6 | Provisioning transport | **Synchronous**; final status returned in-response; async promotion documented, not built |
| O7 | Instructions | **Generated template + seller-editable free text**; ~4k cap, sanitized, versioned; never on the card |
| O8 | Policy model | **Global caps only**: `max_discount_bps` (default 1000), `autonomy_mode` (default `policy_bounded`), fixed escalation trio; per-product floors stay in catalog |
| O9 | Test checks | **Real minimum set** (auth / catalog SKU / pricing bounds / mediated A2A / authority ceiling / revoked credential denied) against sandbox; placeholders removed |
| O10 | Portal | **`/seller/agent` reuses wizard components** for edit-in-place; no forked UI |
| O11 | Gates | **Provision at `pending|verified`; activate at `verified`** + no drift + passing test + active credential |
| O12 | Concurrency | **Optimistic compare-and-swap** on `expected_config_version`; `409` + latest version on mismatch |
| O13 | Card transparency | **Read-only card preview** on testing/activation; exactly what buyers will see |
| O14 | Capability defaults | **ALL ON at onboarding** (accepted divergence) |
| O15 | Credential UX | **Status metadata only**; rotation deferred to post-activation hardening |
| O16 | Config write path | **Runtime-owned via `/internal/agent-configs`** (service auth); control plane records `policy_version`/`policy_hash`; seller store authoritative |
| O17 | Acceptance gate | **Full fresh-org walkthrough + integration/retry/scoping tests** (B.8) |
| O18 | Milestone boundary | **Minimal shared-runtime slice in scope** (config resolution + `/internal/agent-configs` + real checks); cutover stays in this document's §10 |
| O19 | New-org catalog | **Superseded by O25** — no built-in seed |
| O20 | Integrations scope | **Minimal file-import slice in scope**; external sync stays stub (amends O2) |
| O21 | Import formats | **JSON + YAML, content-sniffed**; one canonical import schema |
| O22 | Catalog storage | **Normalized `products` table**; composite PK `(organization_id, sku)`; full model optional-defaults |
| O23 | Import validation | **Strict all-or-nothing** (floor ≤ initial ≤ list, dup SKUs rejected, ≤2MB/≤1000 SKUs, zero writes on failure); upsert by SKU; full replace only via explicit flag + confirm |
| O24 | Import write path | **Runtime-owned `/internal/catalog/import`** (service auth); inventory synced in the same transaction; idempotent replay |
| O25 | O19 disposition | **Auto-seed removed**; bundled `example-catalog.json`/`.yaml` + one-click import in UI |
| O26 | Products schema | **Full SellerPolicy product model**, optional-with-defaults; `organization_id` only on products; `agent_id` not applicable |
| O27 | Catalog hash | **No catalog hash**; activation checks re-run live; §12.5 drift stays bound to `policy_hash` + `card_hash` |
