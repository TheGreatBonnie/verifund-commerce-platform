# Verifund Neon PostgreSQL — Target Design

Date: 2026-11-06
Status: Design for approval. No code or schema changes are made by this document.
Related docs:
- `docs/superpowers/specs/verifund-neondb-implementation-recommendation.md` (source recommendation)
- `docs/superpowers/specs/2026-11-06-verifund-multi-tenancy-design.md` (tenancy model and decisions)
- `docs/superpowers/plans/2026-11-06-verifund-multi-tenancy-implementation.md` (M8 RLS plan)
- `docs/architecture.md` (service ownership)

Related code: `apps/verifund_control_plane`, `apps/buyer_agent`, `apps/seller_agent`,
`apps/registry`, `apps/verifund_agent`, `apps/orchestrator_agent`,
`packages/commerce_core`, `tests`.

## 1. Purpose

Move every Verifund service from SQLite to Neon PostgreSQL. The target is a
single Neon project with a separate database per bounded context and per-service
roles. The control plane and buyer agent enforce row-level security (RLS); the
seller, registry, and single-tenant agent runtimes rely on database and role
isolation where RLS would add no security.

This document records the design decisions made during the Neon grill session.
It is deliberately explicit about what is **not** changing: API contracts for
business keys, integer cents, service ownership boundaries, and the existing
Clerk/tenancy model.

## 2. Decisions locked

| # | Decision | Choice |
|---|---|---|
| 1 | Neon topology | One Neon project; one database per bounded context; one role set per service |
| 2 | Migration scope | All services move to PostgreSQL in this program, not just the control plane |
| 3 | Schema strategy | Full relational normalization within the boundary in §4.3 |
| 4 | Identifier model | Native UUIDs for generated entity IDs; TEXT for business keys, provider IDs, hashes, and composite keys |
| 5 | Existing data | Start Neon clean; do not migrate local SQLite rows or checkpoints |
| 6 | JSON strategy | Normalize genuinely relational collections; keep derived read models and opaque documents as JSONB |
| 7 | RLS timing | Enforce RLS at cutover, not in a later M8-only change |
| 8 | RLS scope | Control plane business graph plus org-scoped tables; buyer agent tables that carry `organization_id`; no RLS where the service is single-tenant |
| 9 | Transaction model | Request-scoped unit of work for RLS-enforced services; short, explicit transaction boundaries around external provider calls |
| 10 | Driver and pooling | `psycopg` 3; pooled endpoint for app traffic; direct endpoint for migrations and checkpoint savers |
| 11 | Test database | PostgreSQL for every service; no dual-dialect control-plane path |
| 12 | Agent state | Separate databases per stateful service; `AsyncPostgresSaver`, ADK `DatabaseSessionService`, and A2A `DatabaseTaskStore` |
| 13 | Checkpoint isolation | Application-level authorization for buyer checkpoints; documented exception to the RLS rule |

Decision 2 supersedes the earlier "control plane first" sequencing. The
implementation phases in §10 are an internal staging order, not a reduction in
scope.

## 3. Target topology

### 3.1 Databases

One Neon project. Each database has its own schema history and role grants.

| Database | Owner service | RLS | Notes |
|---|---|---|---|
| `verifund_control_plane` | control plane | Yes | Transactions, agreements, evidence, tenancy, audit |
| `verifund_buyer` | buyer agent | Yes | Runs, traces, settlement projections, A2A tasks |
| `verifund_seller_northwind` | seller agent | No | One database per seller deployment |
| `verifund_seller_circuitforge` | seller agent | No | Same schema template |
| `verifund_seller_aurora` | seller agent | No | Same schema template |
| `verifund_seller_summit` | seller agent | No | Same schema template |
| `verifund_registry` | registry | No | Global directory; public reads, privileged writes |
| `verifund_agent` | Verifund agent | No | A2A task store |
| `buyer_checkpoints` | buyer agent | No | LangGraph checkpoint tables; tenant-prefixed thread IDs |
| `verifund_checkpoints` | Verifund agent | No | LangGraph checkpoint tables |
| `orchestrator_sessions` | orchestrator | No | ADK sessions, events, app/user state |

Seller databases are created from one schema template. A deployment script
applies the same Alembic revision to each seller database.

### 3.2 Roles and grants

PostgreSQL roles in Neon are **project-level**, not database-level. Create a
role per service and grant `CONNECT` only on that service's database:

```sql
REVOKE CONNECT ON DATABASE verifund_control_plane FROM PUBLIC;
GRANT CONNECT ON DATABASE verifund_control_plane TO cp_app, cp_auth, cp_service;
```

For each service:

| Role | Purpose | Privileges |
|---|---|---|
| `<service>_migrator` | Owns schema, runs Alembic/DDL | Database owner or schema owner; never used at runtime |
| `<service>_app` | Normal request traffic | `CONNECT`, `USAGE` on schema, DML on app tables; not table owner; no `BYPASSRLS` |
| `<service>_service` | Background jobs, webhooks, platform admin | `BYPASSRLS`, DML on all tables; only used on explicitly privileged paths |
| `<service>_auth` | Control-plane identity resolution | `SELECT` only on identity tables; no business-table access |
| `seller_<name>_app` | One seller deployment | DML on its own seller database only |

Rules:
- `neondb_owner` is **not** an application role. Rotate its password if the
  current `.env` URL exposed it.
- `REVOKE ALL ON DATABASE ... FROM PUBLIC` and grant `CONNECT` explicitly.
- `ALTER DEFAULT PRIVILEGES` so future tables created by the migrator grant the
  expected DML to the app role.
- App roles do not own tables. `FORCE ROW LEVEL SECURITY` is still enabled so
  ownership cannot silently bypass policies.
- `BYPASSRLS` is cluster-level; a service role with it must be limited by table
  grants and network/secret access.

### 3.3 Connection URLs

Use two URLs per database:

| Purpose | Endpoint | SQLAlchemy URL |
|---|---|---|
| App traffic | Neon `-pooler` endpoint | `postgresql+psycopg://...` |
| Migrations, checkpoint savers, ADK sessions | Direct endpoint | `postgresql+psycopg://...` |

Suggested settings:

```text
VERIFUND_DATABASE_URL=postgresql+psycopg://cp_app:...@...-pooler.../verifund_control_plane
VERIFUND_DATABASE_URL_UNPOOLED=postgresql+psycopg://cp_migrator:...@.../verifund_control_plane

VERIFUND_BUYER_DATABASE_URL=...
VERIFUND_BUYER_DATABASE_URL_UNPOOLED=...
VERIFUND_SELLER_DATABASE_URL=...
VERIFUND_SELLER_DATABASE_URL_UNPOOLED=...
VERIFUND_REGISTRY_DATABASE_URL=...
VERIFUND_AGENT_DATABASE_URL=...
VERIFUND_AGENT_CHECKPOINT_URL=...
VERIFUND_BUYER_CHECKPOINT_URL=...
VERIFUND_ORCHESTRATOR_SESSION_URL=...
```

Do not reuse a generic `DATABASE_URL` fallback across services. Each service
must fail fast if its own URL is missing rather than silently connecting to
another service's database.

## 4. Schema rules

### 4.1 Generated entity IDs become native UUIDs

Use SQLAlchemy `Uuid(as_uuid=False)` so PostgreSQL stores a native `uuid` while
Python continues to pass and receive strings. Generate with `str(uuid4())`.

Convert:
- `transactions.transaction_id`, `agreements.agreement_id`,
  `agreement_decisions.decision_id`, `agreement_change_requests.change_request_id`,
  `evidence.evidence_id`, `evidence_submissions.submission_id`,
  `requirement_declarations.declaration_id`,
  `provider_operations.operation_id`, `ledger_entries.entry_id`,
  `payout_items.item_id`, `audit_log.audit_id`, `reconciler_runs.run_id`,
  `checkout_links.jti`, `agreement_approval_tokens.jti`, `users.id`,
  `organizations.id`, `organization_members.id`, `organization_invitations.id`,
  `seller_verifications.id`, `agents.id`, `agent_credentials.id`,
  `agent_credentials.agent_id`, `agent_test_runs.id`, `agent_test_runs.agent_id`,
  `payment_accounts.id`, `payout_releases.id`,
  `seller_onboarding.organization_id`, and `platform_admins.user_id`.

Do **not** convert:
- Business keys: `seller_id`, `buyer_id`, `offer_id`, organization slugs.
- A2A/protocol identifiers: `task_id`, `context_id`, `run_id` where it is
  externally supplied, `order_id`.
- Provider identifiers: PayPal order/capture/webhook IDs, Clerk user/org IDs.
- Hashes and natural keys: `jti_hash`, `sha256`, `payload_hash`,
  `idempotency_key`, `(scope, key)`, `(transaction_id, seq)`.
- Free-text actors: `actor`, `actor_id`, `actor_type`, `issued_by_actor_id`.

Replace prefix generation (`vf_`, `agr_`, `dec_`, `cr_`, `sub_`, `ev_`, `op_`,
`le_`, `aud_`, `decl_`, `rec_`) with raw UUID strings. Business-key columns keep
their text values, so `transactions.seller_id` can still reference
`seller_profiles.seller_id` with a text foreign key.

The system principal gets a fixed UUID constant, for example
`00000000-0000-0000-0000-000000000001`. Seed the system user with
`clerk_user_id = 'system'`; `SYSTEM_IDENTITY.user_id` uses the same constant.
System paths run on the service engine, not the tenant app engine.

### 4.2 Timestamps

Use `TIMESTAMPTZ` and a shared `UTCDateTime` TypeDecorator in
`packages/commerce_core`:

- `process_bind_param`: accept `datetime` or ISO-8601 string; reject or
  normalize naive datetimes explicitly.
- `process_result_value`: return a UTC ISO-8601 string, preserving the current
  string-based API and repository behavior.
- `impl = DateTime(timezone=True)`, `cache_ok = True`.

This gives native PostgreSQL timestamp storage without rewriting every
Pydantic model, comparison, and JSON serializer. All timestamps are UTC.

### 4.3 JSON and normalization boundary

Full normalization applies to **relational** data, not to every JSON document.

Normalize:
- `requirement_declarations.submission_ids` becomes a
  `requirement_declaration_submissions` join table with foreign keys to
  `requirement_declarations` and `evidence_submissions`. Remove the JSON array.

Keep as JSONB:
- `transactions` projection columns: `buyer_agent_review`, `seller_decision`,
  `approval`, `cancellation`, `funding`, `purchase_order`, `evidence_summary`,
  `verification`, `dispute`, `payout`, `tracker`, `receipt`, `deadlines`,
  `last_error`. These are a derived read model; `transaction_events` remains the
  normalized source of truth.
- Event and provider documents: `transaction_events.payload`,
  `agreement_events.payload`, `provider_operations.request/response`,
  `webhook_events.payload`, `audit_log.payload`, `reconciler_runs.stats`,
  `payout_items.raw`, `idempotency_keys.response`.
- Small sets read and written as a unit: token/credential `scopes`,
  `seller_onboarding.completed_steps`, `seller_verifications.documents`.
- Document snapshots: `agreement_versions.terms`, `agreement_versions.rendered_html`,
  `agreement_change_requests.operations`, `agreement_decisions.authority_snapshot`.

Use PostgreSQL `JSONB`, not `JSON`, for app-owned columns.

### 4.4 Foreign keys and constraints

- Add foreign keys **within each database only**. Cross-database references
  such as buyer/seller transactions to control-plane entities cannot be
  database-enforced; validate them in the application.
- `transactions.agreement_id` and `agreements.transaction_id` form a cycle. Make
  the foreign keys `DEFERRABLE INITIALLY DEFERRED` and keep both columns
  `NOT NULL`; or make `transactions.agreement_id` nullable and set it after the
  agreement insert. Prefer deferrable constraints so one unit of work can create
  both rows atomically.
- Text business-key foreign keys:
  `transactions.seller_id -> seller_profiles.seller_id`,
  `transactions.buyer_id -> buyer_profiles.buyer_id`,
  `agreements.seller_id/buyer_id` likewise.
- Organization foreign keys: `transactions.buyer_organization_id`,
  `transactions.seller_organization_id`, `agreements.*_organization_id`,
  `evidence.organization_id`, `audit_log.organization_id`, and all org-scoped
  tenancy tables reference `organizations.id`.
- Child rows reference parent entity IDs with `ON DELETE RESTRICT` for financial
  records. Use `CASCADE` only for purely derived join rows that have no audit
  value.
- Add `CHECK` constraints for money (`>= 0`), version/sequence (`>= 0`),
  currency shape, and critical status/state values. Convert integer flags such
  as `webhook_events.verified` and `seller_operator_required` to `BOOLEAN`.
- Keep integer cents. Do not introduce decimal money.

### 4.5 Notable table changes

| Table | Change |
|---|---|
| `transactions` | UUID PK; org UUID FKs; 13 JSON columns to JSONB; timestamps to TIMESTAMPTZ; text seller/buyer FKs |
| `agreements` | UUID PK; UUID transaction FK; deferrable cycle; text business keys; TIMESTAMPTZ |
| `agreement_versions` | UUID `agreement_id`; `change_request_id` UUID nullable; terms/html remain text |
| `agreement_decisions` | UUID `decision_id`; UUID agreement/change-request references; actor text |
| `transaction_events` | UUID transaction FK; JSONB payload; composite PK retained |
| `requirement_declarations` | `submission_ids` JSON removed; join table added |
| `users` / `organizations` | UUID PKs; Clerk IDs remain text unique |
| `seller_profiles` / `buyer_profiles` | Text PKs retained; organization UUID FK |
| `audit_log` | UUID audit ID; nullable UUID transaction/org/`actor_user_id` references; system actors use `NULL` plus `actor_type='system'`; service-only platform rows |
| `fake_orders` / `webhook_events` | Provider IDs remain text; payloads JSONB |
| Seller `seller_agreement_reviews` | Consolidated into `SellerStore`; remove raw `sqlite3` store |
| Buyer `runs` / `trace_events` | `organization_id` UUID NOT NULL; local run/task IDs stay text where externally supplied |
| Registry `sellers` / `seller_listings` / `agents` | Text business IDs retained; `organization_id` UUID nullable metadata; no cross-DB FK |

## 5. RLS and tenancy

### 5.1 Control-plane roles and paths

- `cp_auth`: resolves Clerk identity to local user/organization using `SELECT`
  on `users`, `organizations`, `organization_members`, and `platform_admins`
  before a tenant is known.
- `cp_app`: all normal tenant-scoped requests. RLS enforced.
- `cp_service`: reconciler, PayPal webhooks, platform admin, and other explicit
  cross-tenant paths. `BYPASSRLS`; every use is audited.
- `cp_migrator`: DDL and Alembic only.

Identity endpoints use `cp_auth`; business endpoints use `cp_app`; background
and webhook paths use `cp_service`.

### 5.2 Request-scoped unit of work

Implement a `UnitOfWork` that owns one `AsyncConnection` and one transaction:

1. Resolve identity through `cp_auth`.
2. Open a `cp_app` connection and begin a transaction.
3. Execute
   `select set_config('app.tenant_id', :tenant_id, true)` and
   `select set_config('app.user_id', :user_id, true)` **inside** the
   transaction.
4. Yield the connection/UoW to repositories.
5. Commit on success; roll back on any exception.

Repositories accept the connection and never call `engine.begin()` themselves.
`set_config(..., true)` is transaction-local, so pooled connections cannot leak
tenant context.

Fail closed: if `app.tenant_id` is unset,
`current_setting('app.tenant_id', true)` is `NULL`; policies match no rows.

### 5.3 Policy matrix

Enable `ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` on:

**Dual-organization tables**
- `transactions`
- `agreements`

Policy:

```sql
buyer_organization_id = current_setting('app.tenant_id', true)::uuid
OR seller_organization_id = current_setting('app.tenant_id', true)::uuid
```

Use the same expression in `USING` and `WITH CHECK`.

**Single-organization tables**
- `seller_profiles`, `buyer_profiles`
- `seller_onboarding`, `seller_verifications`
- `agents`, `agent_credentials`, `agent_test_runs`
- `payment_accounts`, `payout_releases`
- `organization_invitations`
- `organizations`

Policy: `organization_id = current_setting('app.tenant_id', true)::uuid`
(or `id = ...` for `organizations`).

**Child tables without an organization column**

Use an indexed `EXISTS` against the parent:

```sql
EXISTS (
  SELECT 1 FROM transactions t
  WHERE t.transaction_id = child.transaction_id
    AND (
      t.buyer_organization_id = current_setting('app.tenant_id', true)::uuid
      OR t.seller_organization_id = current_setting('app.tenant_id', true)::uuid
    )
)
```

Apply to `transaction_events`, `ledger_entries`, `evidence_submissions`,
`provider_operations`, `payout_items`, `receipts`, `seller_tokens`,
`buyer_tokens`, `invitation_tokens`, `checkout_links`, and
`requirement_declaration_submissions` (via declaration -> transaction).

Agreement children use the same pattern against `agreements`.

`evidence` uses `organization_id = tenant OR EXISTS (...)` so
system-attributed evidence with a null organization remains reachable through
its transaction. `audit_log` uses the same org-or-parent rule; platform-level
audit rows with no transaction/org are service-only.

**Service-only tables (no RLS, no `cp_app` grants)**
- `idempotency_keys`
- `webhook_events`
- `reconciler_runs`
- `fake_orders` (test/dev only; service role only)

**Auth-role tables**
- `users`
- `organization_members`
- `platform_admins` (auth role `SELECT`; service role DML)

Business endpoints that need member display data go through the auth repository,
not `cp_app`.

### 5.4 Buyer-agent RLS

Enable RLS on:
- `runs`: `organization_id = tenant`
- `trace_events`: `organization_id = tenant`
- `settlement_projections`: `EXISTS` through `runs.run_id`
- `run_secrets`: `EXISTS` through `runs.run_id`
- `tasks` (A2A `DatabaseTaskStore`): policy on `owner`, configured so the
  owner resolver writes `organization_id` rather than a user ID

The buyer service uses the same request-scoped UoW and `set_config` pattern.

### 5.5 Checkpoint isolation exception

`buyer_checkpoints` is not under RLS. LangGraph's `AsyncPostgresSaver` owns its
connection pool and internal SQL, and its schema does not carry an organization
column. Isolation relies on:
- thread IDs formatted as `${organization_id}:${run_id}`;
- `authorize_run_stream` and related run-level checks rejecting a run whose
  `organization_id` does not match the caller.

Document this exception and add tests proving a foreign organization cannot
authorize or read a run. Revisit only if LangGraph exposes a stable
tenant-aware connection hook.

### 5.6 Services without RLS

- Seller databases: one database and one app role per seller; no shared
  database. `REVOKE CONNECT` from other roles.
- Registry: global directory; public reads, privileged writes. No RLS.
- Verifund agent and orchestrator: single-tenant runtimes; no RLS.

## 6. Runtime and connection model

### 6.1 Driver and pool

- `postgresql+psycopg` (psycopg 3) for both async app traffic and sync Alembic.
- App engine: Neon pooled endpoint, `pool_pre_ping=True`,
  `pool_recycle=300`, `pool_size=5`, `max_overflow=10`, `pool_timeout=30`.
- Pass `connect_args={"prepare_threshold": None}` for PgBouncer transaction
  pooling. Set `application_name` for observability.
- Migrations and checkpoint savers use the direct endpoint.
- Role-level timeouts:
  `idle_in_transaction_session_timeout = '30s'`,
  `statement_timeout = '30s'`, `lock_timeout = '5s'`.

### 6.2 External provider calls

A request-scoped transaction must **not** span a PayPal HTTP call. Use explicit
phases:

1. UoW 1: read state, insert a `provider_operations` row with the idempotency
   key and `status='pending'`; commit.
2. Call PayPal outside any transaction.
3. UoW 2: record the response, update the operation and transaction projection;
   commit.

The request-scoped UoW supports explicit `commit()`/`begin()` boundaries for
these flows. Idempotency keys and the reconciler make retries safe.

### 6.3 Streaming and background work

- Do not hold a UoW across SSE/streaming responses. Commit before yielding;
  use short UoWs for later database reads.
- Reconciler and webhook workers create a service UoW per iteration/event.
- Use `SELECT ... FOR UPDATE SKIP LOCKED` when claiming work.
- Retry SQLSTATE `40001` (serialization failure) and `40P01` (deadlock) with
  jittered backoff. Keep the existing optimistic `version`/`last_seq` checks for
  business invariants.

## 7. Service-by-service scope

### 7.1 Control plane

- Rewrite `repository.py`, `tenancy/repository.py`, and
  `agreements/repository.py` for PostgreSQL types, `pg_insert`, and UoW-bound
  connections.
- Replace `db.py` SQLite PRAGMA/transaction handling with PostgreSQL engine and
  retry helpers.
- Remove `create_schema()`/`metadata.create_all` and
  `tenancy/backfill.py` PRAGMA migrations. Schema comes from Alembic.
- Add RLS migrations, roles, policies, and grants.
- Update `SYSTEM_IDENTITY`, user seeding, and audit actor handling for the fixed
  system UUID.
- Add RLS tests for buyer/seller shared visibility, cross-tenant denial,
  `WITH CHECK`, service bypass, and auth-role boundaries.

### 7.2 Buyer agent

- Move `runs`, `run_secrets`, `settlement_projections`, `trace_events`, and the
  A2A `tasks` table to `verifund_buyer`.
- Add `organization_id` UUID NOT NULL where missing; keep external run/task IDs
  text.
- Apply RLS and the request-scoped UoW to HTTP/console paths. Graph execution
  uses short transactions around database writes, never around LLM calls.
- Configure `DatabaseTaskStore` with a tenant-aware owner resolver.
- Replace `AsyncSqliteSaver` with `AsyncPostgresSaver` in `buyer_checkpoints`;
  use the direct endpoint. Keep app-level checkpoint authorization.

### 7.3 Seller agents

- Create one database per seller from an Alembic schema template.
- Port inventory, offers, orders, settlement tokens, evidence outbox,
  `seller_agreement_reviews`, and A2A `tasks` to PostgreSQL.
- Consolidate `SellerAgreementReviewStore` into `SellerStore`; remove the raw
  `sqlite3` store and the separate `data/seller_agreement_reviews.db`.
- Keep `MemorySaver` for seller graphs unless a durable checkpoint requirement
  appears.
- No RLS; isolate by database and role.

### 7.4 Registry

- Port `sellers`, `seller_listings`, and `agents` to PostgreSQL.
- Keep text seller/agent business IDs; store `organization_id` as nullable UUID
  metadata without a cross-database foreign key.
- Public reads; writes require the admin/service path.

### 7.5 Verifund agent and orchestrator

- Verifund agent: `verifund_agent` database for `DatabaseTaskStore`;
  `verifund_checkpoints` for `AsyncPostgresSaver`.
- Orchestrator: `orchestrator_sessions` database for ADK
  `DatabaseSessionService`. Remove the SQLite path parsing in
  `orchestrator_agent/__main__.py`.
- Both are single-tenant; no RLS.

## 8. Migrations and schema ownership

- Add Alembic to the project dependencies and create one migration environment
  per app-owned database: control plane, buyer, seller template, registry,
  Verifund agent.
- The initial revision creates the complete schema. Do not keep
  `metadata.create_all` or `PRAGMA table_info` migrations in runtime code.
- Run `alembic upgrade head` as a deploy step with the migrator role. The app
  verifies the revision at startup and fails fast on a mismatch; it does not
  auto-migrate.
- Seller migrations run once per seller database. A script iterates the seller
  URLs and applies the same revision.
- Library-owned tables:
  - A2A `DatabaseTaskStore`: create via its `initialize()` at deploy with the
    migrator role; run the app with `create_table=False`.
  - LangGraph: `AsyncPostgresSaver.setup()` at deploy; app uses the saver.
  - ADK `DatabaseSessionService`: create its tables at deploy with the migrator
    role, or let the service create them once before the app role is granted
    DML.
- Ordering: run library-owned table creation **before** any RLS migration that
  adds policies to those tables (notably buyer A2A `tasks`). The deploy script
  should fail if a policy references a missing table.
- Seed script: fixed system user UUID, demo organizations/profiles, and registry
  seed data. No transaction history. Local SQLite files remain untouched and
  are not read by the new services.
- Remove SQLite-specific dependencies and code once every service is migrated:
  `aiosqlite`, `langgraph-checkpoint-sqlite`, `configure_sqlite`,
  `sqlite_insert`, `sqlite3` imports, and the `a2a-sdk[sqlite]` extra.

## 9. Test strategy

- Add a PostgreSQL 18 service (Docker Compose locally, service container in CI).
  Create one test database per service, each name ending in `_test`.
- Add a guard that refuses to truncate/drop a database whose name does not end
  in `_test`.
- Pytest fixtures:
  - session-scoped engine and migration runner per service;
  - per-test transaction rollback for repository tests;
  - truncate/reset for UoW and RLS tests that must commit;
  - FastAPI client fixture that overrides the UoW dependency.
- Convert every control-plane, buyer, seller, registry, Verifund-agent, and
  orchestrator database test from `sqlite+aiosqlite` to PostgreSQL.
- RLS test matrix:
  - buyer org sees its transactions and child rows;
  - seller org sees the same shared transaction and its own rows;
  - unrelated org sees nothing;
  - `WITH CHECK` rejects cross-tenant inserts/updates;
  - missing `app.tenant_id` fails closed;
  - service role sees all; auth role cannot read business tables;
  - tenant context does not leak across pooled connections.
- Buyer checkpoint tests: foreign organization cannot authorize a run or read
  its checkpoint.
- Keep non-database unit tests as they are; only database-backed tests move.
- Run `EXPLAIN` on the main RLS child-table policies and add indexes on
  `transaction_id`, `agreement_id`, and `organization_id` before cutover.

## 10. Implementation phases

These are staging phases inside the all-services scope.

### Phase 0 — Foundation

- Add `psycopg[binary,pool]`, Alembic, and `langgraph-checkpoint-postgres`.
- Add the `UTCDateTime` and UUID helpers in `commerce_core`.
- Add PostgreSQL settings, per-service URLs, and startup revision checks.
- Add Docker Compose PostgreSQL 18, test databases, roles, and CI service.
- Add the `UnitOfWork` skeleton and `set_config` helper.
- **Exit:** a trivial async test connects to PostgreSQL and sets/reads
  `app.tenant_id`; no service schema has changed yet.

### Phase 1 — Control plane

- Write the initial Alembic schema with UUIDs, TIMESTAMPTZ, JSONB, FKs,
  join table, checks, and indexes.
- Refactor repositories to UoW-bound connections and `pg_insert`.
- Add `cp_app`, `cp_auth`, `cp_service`, and `cp_migrator` roles, grants, and RLS
  policies.
- Update identity, system UUID, audit, webhooks, reconciler, and provider-call
  boundaries.
- Convert control-plane tests to PostgreSQL; add the RLS matrix.
- **Exit:** control-plane tests pass on PostgreSQL; the lifecycle smoke test
  passes with fake PayPal; RLS denies cross-tenant access.

### Phase 2 — Buyer agent

- Create the buyer schema and Alembic revision.
- Add `organization_id` and RLS; add the request-scoped UoW.
- Configure the tenant-aware A2A task owner and move checkpoints to
  `AsyncPostgresSaver`.
- Convert buyer tests and add checkpoint authorization tests.
- **Exit:** buyer tests pass; org A cannot see org B's runs, traces, tasks, or
  settlement projections.

### Phase 3 — Seller agents

- Create the seller schema template and apply it to each seller database.
- Port stores to PostgreSQL; consolidate `seller_agreement_reviews`; remove the
  raw `sqlite3` store.
- Configure the A2A task store and per-seller roles.
- Convert seller tests and add per-seller isolation tests.
- **Exit:** every seller database migrates independently; one seller role cannot
  connect to another seller database.

### Phase 4 — Registry, Verifund agent, orchestrator

- Port registry stores and tests.
- Move Verifund agent task store and checkpoints.
- Move ADK sessions to `DatabaseSessionService` with PostgreSQL; remove SQLite
  path handling.
- Convert tests.
- **Exit:** all service tests pass on PostgreSQL; checkpoint and session
  persistence survives a restart.

### Phase 5 — Cutover

- Apply migrations to the Neon project; seed the system principal and demo data.
- Deploy all services with PostgreSQL URLs; run the end-to-end lifecycle and
  smoke scripts.
- Run RLS, checkpoint, and per-seller isolation checks against the deployed
  databases.
- Remove SQLite dependencies and configuration; keep local SQLite files as
  read-only legacy artifacts.
- Rotate exposed credentials; confirm Neon backup/PITR retention and rehearse a
  restore.
- **Exit:** all services run on Neon; no runtime path writes SQLite; rollback to
  the previous deployment is documented and tested.

## 11. Relationship to the Neon recommendation

Adopt:
- Neon PostgreSQL, separate databases per service, pooled app/direct migration
  URLs, `psycopg`, Alembic, and RLS.
- Per-service roles and least-privilege grants.

Defer:
- Redis and a general outbox beyond `provider_operations`.
- Multi-region/read-replica tuning.
- Shredding every JSON document into tables.

Reject:
- One shared schema for all services.
- `metadata.create_all` as the production migration mechanism.
- `neondb_owner` as the application role.
- A generic `DATABASE_URL` that lets one service silently connect to another
  service's database.

## 12. Risks and open items

1. **Request-scoped UoW plus PayPal calls** is the largest correctness risk.
   Mitigate with explicit commit/call/commit phases and `provider_operations`
   idempotency.
2. **RLS child policies** can be slow. Index parent keys and measure with
   `EXPLAIN` before cutover.
3. **Test migration** is broad: nearly every database test currently uses
   SQLite. Budget for it explicitly.
4. **Library-owned schemas** (A2A, LangGraph, ADK) can drift on upgrade. Pin
   versions and run their setup in a deploy step.
5. **Neon connection limits** and PgBouncer prepared statements. Use the pooled
   endpoint for app traffic, direct for migrations/savers, and
   `prepare_threshold=None`.
6. **Big-bang all-services cutover.** Stage internally and run the new stack in
   parallel before switching traffic.
7. **Seller database proliferation.** Automate creation and migration from the
   template; do not hand-edit seller databases. A database per seller fits the
   current four seeded sellers, but self-serve seller onboarding at scale would
   make per-seller provisioning expensive. Revisit a shared seller database with
   `seller_id` RLS before onboarding becomes self-serve.
8. **Checkpoint exception.** Buyer checkpoints rely on application-level
   authorization. Keep the run-level check tested.
9. **Circular foreign keys** between transactions and agreements. Use deferrable
   constraints and test the create path.
10. **Credential exposure.** The current `.env` contains a pooled owner URL.
    Rotate it and never use the owner role at runtime.

Open choices to confirm during implementation:
- Whether to adopt UUIDv7 for time-ordered inserts (UUIDv4 is sufficient at
  current scale).
- Whether to add CHECK constraints for every status value or only critical
  money/lifecycle states after auditing current values.
- Whether to keep local SQLite files indefinitely as read-only archives or
  delete them after a successful cutover.

## 13. Approval gate

No code, schema, or migration changes until this design is approved. After
approval, the next deliverable is a task-by-task implementation plan with
failing tests first, service by service.
