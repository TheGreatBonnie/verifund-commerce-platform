# Multi-Tenancy Design for MarketMesh (Verifund A2A)

**Status:** Design spec (pending implementation)
**Date:** 2026-10-28
**Audience:** Implementation team
**Scope:** User-level multi-tenancy with data isolation

---

## 1. Overview

MarketMesh is currently a single-identity prototype: one demo buyer, three sellers, and a platform-level PayPal account. Multi-tenancy at the **user level** means every human user (buyer or seller operator) gets their own isolated data space within a shared deployment, backed by a real identity provider.

### Primary goal
Data isolation: each user sees only their own runs, orders, traces, and settlement data. No cross-user data leakage.

### Tenant boundary
**User-level.** Each authenticated human user is a tenant. A user may act as a buyer, a seller operator (for one or more sellers), or an admin.

### Authorization model
Role-based: `buyer`, `seller-operator`, `admin`. Roles determine which services and data a user can access.

---

## 2. Identity & User Model

### Identity provider
Add a real identity provider (Clerk or Auth0) with JWT-based authentication. The console integrates the provider's SDK for login/logout. All backend services validate JWTs and extract `user_id` + `role`.

The existing `.env` bearer-token model is replaced.

### User table
```sql
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    role          TEXT NOT NULL CHECK (role IN ('buyer', 'seller-operator', 'admin')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

### Auth flow
1. User logs in via the console (identity provider SDK).
2. Console receives a JWT and stores it in session.
3. Console sends the JWT in the `Authorization: Bearer <token>` header to the orchestrator.
4. Orchestrator validates the JWT, extracts `user_id` and `role`.
5. Orchestrator forwards `X-User-Id` and `X-User-Role` headers to downstream services.
6. Each service validates these headers (or trusts the orchestrator's validated context) and scopes all data access.

---

## 3. Data Isolation per Service

Each service adds a `user_id` (or `owner_id`) column to its core tables and filters all queries by the authenticated user.

### Buyer agent
| Table | New column | Filter |
| --- | --- | --- |
| `runs` | `user_id` | `WHERE user_id = :current_user` |
| `a2a_trace_frames` | `user_id` (via run) | Join to `runs` on `run_id` |
| `langgraph_checkpoints` | `user_id` (via run) | Join to `runs` on `thread_id` |

- Runs are created with the authenticated user's `user_id`.
- The `/runs` list endpoint returns only the current user's runs.
- The `/runs/{runId}` detail endpoint returns 404 if the run does not belong to the current user.

### Seller agents
Sellers remain seller-scoped (catalog, stock, orders belong to the seller, not the user). Access is gated by the `seller_operators` join table (see Section 5).

- A user with no seller links cannot act as a seller.
- Seller services check operator permissions before processing A2A calls.
- Catalog, stock, and orders are shared among a seller's operators.

### Registry
Agent Cards remain global. All authenticated users can discover all sellers. Access control happens at the seller level (seller checks operator permissions before processing calls). This matches the current marketplace model.

### Verifund control plane
| Table | New column | Filter |
| --- | --- | --- |
| `transactions` | `buyer_user_id` | `WHERE buyer_user_id = :current_user OR seller_id IN (user's sellers)` |
| `evidence` | (via transaction) | Join to `transactions` |
| `ledger` | (via transaction) | Join to `transactions` |

- A buyer sees only their own transactions.
- Seller operators see transactions for their seller.
- PayPal credentials remain platform-level (single Business account).
- The webhook receiver routes events by `order_id`/`capture_id` (already works; no change needed).

---

## 4. Cross-Service User Context Propagation

```
Console (JWT) → Orchestrator (validate JWT, extract user_id + role)
                    │
                    ├──► Buyer (X-User-Id, X-User-Role)
                    ├──► Sellers (X-User-Id, X-User-Role)
                    ├──► Registry (X-User-Id, X-User-Role)
                    └──► Verifund (X-User-Id, X-User-Role)
```

- The console sends the user's JWT in the `Authorization` header to the orchestrator.
- The orchestrator validates the JWT, extracts `user_id` and `role`, and forwards them as `X-User-Id` and `X-User-Role` headers to all downstream services.
- Each downstream service validates these headers against its own auth (or trusts the orchestrator's validated context).
- The buyer stores `user_id` in run state; sellers check operator permissions before processing; Verifund scopes transactions by buyer user.

---

## 5. Seller Operator Scoping

### `seller_operators` table
```sql
CREATE TABLE seller_operators (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    seller_id  TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('owner', 'operator', 'viewer')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, seller_id)
);
```

- A user can be linked to one or more sellers.
- Roles: `owner` (full control), `operator` (manage catalog/offers/orders), `viewer` (read-only).
- Seller services check the operator link before processing A2A calls.
- Catalog, stock, and orders remain seller-scoped (shared among operators) but access is gated by the link.

---

## 6. Registry Scoping

The registry remains global. All authenticated users can discover all sellers. Access control happens at the seller level (seller checks operator permissions before processing calls). This matches the current marketplace model and avoids over-complicating discovery.

---

## 7. Verifund Scoping

- Transactions are scoped to the buyer user and the seller's operators.
- A buyer sees only their own transactions.
- Seller operators see transactions for their seller.
- The held-funds ledger and evidence are per-transaction (naturally scoped).
- PayPal credentials remain platform-level (single Business account).
- The webhook receiver routes events by `order_id`/`capture_id` (already works; no change needed).
- The control plane validates that the requesting user is the buyer or a seller operator before returning transaction data.

---

## 8. Console & Orchestrator Changes

- The console integrates the identity provider's SDK for login/logout.
- The runs list and run detail pages filter by the authenticated user.
- The orchestrator validates the JWT and propagates user context to all downstream services.
- The CopilotKit chat includes the user's identity in its context.
- Add a user profile/settings page.

---

## 9. Migration Path

Multi-tenancy is a large change. Proposed phases, each independently deployable:

### Phase 1: Identity provider + users table
- Add Clerk/Auth0 SDK to the console.
- Create the `users` table.
- Existing data is assigned to a default admin user.
- `.env` bearer tokens still work (backward compatible).

### Phase 2: Add user_id columns
- Add `user_id`/`owner_id` columns to all core tables.
- Backfill existing rows with the default admin user's ID.
- Add `seller_operators` table and seed with existing seller-operator mappings.

### Phase 3: Enforce filtering
- Add user filtering to all service queries.
- Add permission checks to seller services.
- Add user context propagation to the orchestrator.

### Phase 4: Remove legacy auth
- Remove the `.env` bearer-token model.
- All services require JWT auth.
- Remove backward-compatibility shims.

---

## 10. Risks & Trade-offs

| Risk | Mitigation |
| --- | --- |
| **Migration complexity** | Phased approach; each phase is independently deployable. |
| **LangGraph checkpoint scoping** | Checkpoints are keyed by `thread_id`; need to add `user_id` to checkpoint metadata or use a composite key. |
| **Seller service auth** | Sellers currently use bearer tokens from `.env`; need to accept both legacy and JWT during migration. |
| **Registry discovery** | Global registry means all users see all sellers; if tenant isolation of discovery is needed later, add visibility flags. |
| **Verifund webhook routing** | Already routes by `order_id`/`capture_id`; no change needed. |
| **Performance** | Adding `user_id` filters to every query adds overhead; index `user_id` columns. |
| **Testing** | Need to update all tests to include user context; significant test churn. |

---

## 11. Non-goals

- Per-user PayPal credentials (platform account only).
- Tenant-level billing or subscription management.
- Cross-tenant data sharing or collaboration.
- Multi-region deployment (single region per tenant).
- Real-time user presence or collaboration features.

---

## 12. Open questions

1. Which identity provider (Clerk, Auth0, or custom) best fits the stack and budget?
2. Should the `users` table live in the buyer DB, a shared auth DB, or a dedicated identity service?
3. How should LangGraph checkpoints be scoped to users (composite thread_id or metadata filter)?
4. Should seller operators be able to belong to multiple sellers, or is it 1:1?
5. What happens to existing demo data (Nimbus NC-700 → Sony WH-1000XM5 migration) during the multi-tenancy migration?
