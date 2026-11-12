# Single Shared A2A Endpoint Cutover — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run all seller agents from one shared process on one A2A endpoint, with per-request tenant resolution and organization-scoped data.

**Architecture:** `seller_agent` gains a `shared` app mode (already started in commit `fa09ca0`) that serves one JSON-RPC A2A route per seller path, resolves the recipient from `SendMessageRequest.tenant` plus the `/{seller_id}/a2a` path, verifies caller credentials against the Verifund control plane, and executes with an `OrgScopedStore` against `data/sellers.db`. Checkpoints live in `data/seller-checkpoints.sqlite`; A2A task ownership is enforced by the SDK `DatabaseTaskStore.owner` column. The dev stack starts one shared seller process on `:9200` instead of four processes on `:9201`–`:9204`.

**Tech Stack:** Python 3.12, FastAPI, `a2a-sdk==1.2.3`, SQLAlchemy async + SQLite, LangGraph + `langgraph-checkpoint-sqlite`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md`

## Global Constraints

- One `seller_agent` process, one port: `127.0.0.1:9200`.
- Canonical A2A path: `/{seller_id}/a2a`; card path: `/{seller_id}/.well-known/agent-card.json`.
- `tenant` value is `agent_<seller_id>`; it is a routing hint, never authorization.
- No seller configuration cache. Credential verification caches only positives for 30 seconds, keyed by token hash.
- Every seller-data query carries `organization_id`; fail closed when org is unset.
- Checkpoint `thread_id` = `organization_id:{organization_id}:{agent_id}:{request_thread_id}`.
- A2A tasks are owned by the verified caller organization via `DatabaseTaskStore.owner`.
- No static `SELLER_*_TOKEN` is accepted on an A2A path.
- SQLite only for this milestone; Neon/PostgreSQL remains deferred.

---

### Task 1: Complete the shared schema

**Files:**
- Modify: `apps/seller_agent/seller_agent/shared_schema.py`
- Test: `tests/unit/test_shared_schema.py`

**Interfaces:**
- Produces: `SHARED_DDL` with `evidence_outbox` columns (`seller_id`, `filename`, `media_type`, `content`, `note`, `captured_at`, `next_attempt_at`, `sent_at`) and `settlement_tokens` columns (`seller_id`, `updated_at`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_schema.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import create_shared_schema


@pytest.mark.asyncio
async def test_evidence_and_settlement_columns_exist(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await create_shared_schema(engine)
    async with engine.connect() as conn:
        evidence = {r[1] for r in await conn.exec_driver_sql("PRAGMA table_info(evidence_outbox)")}
        settlement = {r[1] for r in await conn.exec_driver_sql("PRAGMA table_info(settlement_tokens)")}
    assert {"seller_id", "filename", "media_type", "content", "note", "captured_at",
            "next_attempt_at", "sent_at"} <= evidence
    assert {"seller_id", "updated_at"} <= settlement
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_shared_schema.py::test_evidence_and_settlement_columns_exist -v`
Expected: FAIL because the columns do not exist.

- [ ] **Step 3: Add the columns to `SHARED_DDL`**

Replace the `evidence_outbox` DDL with:

```sql
CREATE TABLE IF NOT EXISTS evidence_outbox (
    organization_id TEXT NOT NULL,
    outbox_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    content BLOB NOT NULL DEFAULT X'',
    note TEXT NOT NULL DEFAULT '',
    captured_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at TEXT,
    agent_id TEXT,
    UNIQUE (organization_id, transaction_id, kind)
)
```

Replace the `settlement_tokens` DDL with:

```sql
CREATE TABLE IF NOT EXISTS settlement_tokens (
    organization_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    seller_id TEXT NOT NULL DEFAULT '',
    token_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (organization_id, transaction_id)
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_shared_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_schema.py tests/unit/test_shared_schema.py
git commit -m "feat(seller-shared): complete shared schema for evidence and settlement"
```

---

### Task 2: Make `OrgScopedStore` cover the full seller data plane

**Files:**
- Modify: `apps/seller_agent/seller_agent/shared_store.py`
- Test: `tests/unit/test_shared_store_scoping.py`

**Interfaces:**
- Produces: `OrgScopedStore` overrides for `create_schema`, `seed_catalog`, `transaction`, `set_stock`, `list_offers`, `list_orders`, `save_order`, `get_order_by_idempotency`, `reserve`, `save_settlement_token`, `get_settlement_token`, `list_settlement_tokens`, `enqueue_evidence`, `list_due_evidence`, `mark_evidence_sent`, `reschedule_evidence`, `fail_evidence`, `get_evidence_outbox`.
- Produces: `OrgScopedTransaction` with `get_offer`, `get_order_by_idempotency`, `reserve`, `save_order`.

- [ ] **Step 1: Write the failing cross-tenant test**

```python
# tests/unit/test_shared_store_scoping.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import create_shared_schema
from seller_agent.shared_store import OrgScopedStore


@pytest.mark.asyncio
async def test_orders_and_offers_are_org_scoped(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await create_shared_schema(engine)
    a = OrgScopedStore(engine, organization_id="org-a", agent_id="agent-a")
    b = OrgScopedStore(engine, organization_id="org-b", agent_id="agent-b")

    await a.set_stock("SKU-1", 10, 0, None)
    assert (await a.get_stock("SKU-1")).on_hand == 10
    assert (await b.get_stock("SKU-1")).on_hand == 0

    assert await a.reserve("SKU-1", 2, allow_split=False) == {
        "split_shipment": False, "on_hand": 8
    }
    assert (await a.get_stock("SKU-1")).on_hand == 8
    assert (await b.get_stock("SKU-1")).on_hand == 0
    await engine.dispose()
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_shared_store_scoping.py -v`
Expected: FAIL — inherited `set_stock`/`reserve` write the unscoped `inventory` table.

- [ ] **Step 3: Implement the overrides**

Add to `shared_store.py`:

```python
class OrgScopedTransaction:
    def __init__(self, store: "OrgScopedStore", conn) -> None:
        self.store = store
        self.conn = conn

    async def get_offer(self, offer_id: str):
        row = (await self.conn.execute(text(
            "SELECT offer_json FROM offers WHERE organization_id=:o AND offer_id=:i"),
            {"o": self.store.organization_id, "i": offer_id})).first()
        return Offer.model_validate(json.loads(row.offer_json)) if row else None

    async def get_order_by_idempotency(self, key: str):
        row = (await self.conn.execute(text(
            "SELECT order_json FROM orders "
            "WHERE organization_id=:o AND idempotency_key=:k"),
            {"o": self.store.organization_id, "k": key})).first()
        return Order.model_validate(json.loads(row.order_json)) if row else None

    async def reserve(self, sku: str, quantity: int, *, allow_split: bool):
        row = (await self.conn.execute(text(
            "SELECT on_hand, incoming, incoming_days FROM inventory "
            "WHERE organization_id=:o AND sku=:s"),
            {"o": self.store.organization_id, "s": sku})).first()
        if row is None:
            raise ValueError("unknown sku")
        if row.on_hand >= quantity:
            await self.conn.execute(text(
                "UPDATE inventory SET on_hand=on_hand-:q "
                "WHERE organization_id=:o AND sku=:s"),
                {"q": quantity, "o": self.store.organization_id, "s": sku})
            return Reservation(split_shipment=False)
        if (allow_split and row.on_hand + row.incoming >= quantity
                and (row.incoming_days is None or row.incoming_days <= 14)):
            remaining = row.on_hand + row.incoming - quantity
            await self.conn.execute(text(
                "UPDATE inventory SET on_hand=0, incoming=:r "
                "WHERE organization_id=:o AND sku=:s"),
                {"r": remaining, "o": self.store.organization_id, "s": sku})
            return Reservation(split_shipment=True)
        raise ValueError("out_of_stock")

    async def save_order(self, order, *, idempotency_key: str) -> None:
        await self.conn.execute(text(
            """INSERT INTO orders (organization_id, order_id, offer_id, seller_id,
                                   idempotency_key, order_json, created_at, agent_id)
               VALUES (:o, :oid, :fid, :sid, :k, :json, :now, :a)"""),
            {"o": self.store.organization_id, "oid": order.order_id,
             "fid": order.offer_id, "sid": order.seller_id, "k": idempotency_key,
             "json": json.dumps(order.model_dump(mode="json")),
             "now": datetime.now(UTC).isoformat(), "a": self.store.agent_id})
```

Add methods to `OrgScopedStore`. Use text SQL with `organization_id = :o` on every statement:

```python
async def create_schema(self) -> None:
    return None

async def seed_catalog(self, policy) -> None:
    return None

@asynccontextmanager
async def transaction(self):
    async with self.engine.begin() as conn:
        yield OrgScopedTransaction(self, conn)

async def set_stock(self, sku, on_hand, incoming=0, incoming_days=None) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(text(
            """INSERT INTO inventory (organization_id, sku, on_hand, incoming, incoming_days)
               VALUES (:o, :s, :oh, :inc, :ind)
               ON CONFLICT(organization_id, sku) DO UPDATE SET
                 on_hand=:oh, incoming=:inc, incoming_days=:ind"""),
            {"o": self.organization_id, "s": sku, "oh": int(on_hand),
             "inc": int(incoming), "ind": incoming_days})

async def list_offers(self, limit=20):
    async with self.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT offer_json, created_at FROM offers WHERE organization_id=:o "
            "ORDER BY created_at DESC LIMIT :n"),
            {"o": self.organization_id, "n": max(1, min(limit, 100))})).all()
    return [{"offer": Offer.model_validate(json.loads(r.offer_json)),
             "created_at": r.created_at} for r in rows]

async def list_orders(self, limit=20):
    async with self.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT order_json, created_at FROM orders WHERE organization_id=:o "
            "ORDER BY created_at DESC LIMIT :n"),
            {"o": self.organization_id, "n": max(1, min(limit, 100))})).all()
    return [{"order": Order.model_validate(json.loads(r.order_json)),
             "created_at": r.created_at} for r in rows]

async def save_order(self, order, *, idempotency_key):
    async with self.transaction() as tx:
        await tx.save_order(order, idempotency_key=idempotency_key)

async def get_order_by_idempotency(self, key):
    async with self.transaction() as tx:
        return await tx.get_order_by_idempotency(key)

async def reserve(self, sku, quantity, *, allow_split):
    async with self.transaction() as tx:
        result = await tx.reserve(sku, quantity, allow_split=allow_split)
    return {"split_shipment": result.split_shipment,
            "on_hand": (await self.get_stock(sku)).on_hand}

async def save_settlement_token(self, transaction_id, seller_id, token):
    async with self.engine.begin() as conn:
        await conn.execute(text(
            """INSERT INTO settlement_tokens
                 (organization_id, transaction_id, seller_id, token_json, updated_at)
               VALUES (:o, :t, :s, :j, :now)
               ON CONFLICT(organization_id, transaction_id) DO UPDATE SET
                 token_json=:j, seller_id=:s, updated_at=:now"""),
            {"o": self.organization_id, "t": transaction_id, "s": seller_id,
             "j": json.dumps({"token": token}), "now": datetime.now(UTC).isoformat()})

async def get_settlement_token(self, transaction_id):
    async with self.engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT token_json FROM settlement_tokens "
            "WHERE organization_id=:o AND transaction_id=:t"),
            {"o": self.organization_id, "t": transaction_id})).first()
    return json.loads(row.token_json)["token"] if row else None

async def list_settlement_tokens(self, limit=5):
    async with self.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT transaction_id, seller_id, updated_at FROM settlement_tokens "
            "WHERE organization_id=:o ORDER BY updated_at DESC LIMIT :n"),
            {"o": self.organization_id, "n": max(1, min(limit, 20))})).all()
    return [dict(r._mapping) for r in rows]

async def enqueue_evidence(self, *, transaction_id, seller_id, kind, content,
                           media_type, filename, note="", captured_at=None,
                           created_at=None) -> bool:
    now = (created_at or datetime.now(UTC)).isoformat()
    async with self.engine.begin() as conn:
        result = await conn.execute(text(
            """INSERT INTO evidence_outbox
                 (organization_id, outbox_id, transaction_id, seller_id, kind,
                  filename, media_type, content, note, captured_at,
                  next_attempt_at, created_at, agent_id)
               VALUES (:o, :id, :t, :s, :k, :f, :m, :c, :n, :cap, :now, :now, :a)
               ON CONFLICT(organization_id, transaction_id, kind) DO NOTHING"""),
            {"o": self.organization_id, "id": uuid.uuid4().hex, "t": transaction_id,
             "s": seller_id, "k": kind, "f": filename, "m": media_type,
             "c": content, "n": note, "cap": captured_at, "now": now,
             "a": self.agent_id})
    return bool(result.rowcount)

async def list_due_evidence(self, *, now, limit=20):
    async with self.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT * FROM evidence_outbox WHERE organization_id=:o "
            "AND status='pending' AND next_attempt_at<=:now "
            "ORDER BY created_at LIMIT :n"),
            {"o": self.organization_id, "now": now,
             "n": max(1, min(limit, 100))})).all()
    return [dict(r._mapping) | {"evidence_key": r.outbox_id} for r in rows]

async def mark_evidence_sent(self, evidence_key, *, sent_at):
    async with self.engine.begin() as conn:
        await conn.execute(text(
            "UPDATE evidence_outbox SET status='sent', sent_at=:s, last_error=NULL "
            "WHERE organization_id=:o AND outbox_id=:id"),
            {"s": sent_at, "o": self.organization_id, "id": evidence_key})

async def reschedule_evidence(self, evidence_key, *, next_attempt_at, error):
    async with self.engine.begin() as conn:
        await conn.execute(text(
            "UPDATE evidence_outbox SET attempts=attempts+1, "
            "next_attempt_at=:n, last_error=:e "
            "WHERE organization_id=:o AND outbox_id=:id"),
            {"n": next_attempt_at, "e": error, "o": self.organization_id,
             "id": evidence_key})

async def fail_evidence(self, evidence_key, *, error):
    async with self.engine.begin() as conn:
        await conn.execute(text(
            "UPDATE evidence_outbox SET status='failed', attempts=attempts+1, "
            "last_error=:e WHERE organization_id=:o AND outbox_id=:id"),
            {"e": error, "o": self.organization_id, "id": evidence_key})

async def get_evidence_outbox(self, transaction_id, kind):
    async with self.engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT * FROM evidence_outbox WHERE organization_id=:o "
            "AND transaction_id=:t AND kind=:k"),
            {"o": self.organization_id, "t": transaction_id, "k": kind})).first()
    return dict(row._mapping) if row else None
```

Add the missing imports: `asynccontextmanager`, `uuid`, `Order`, `Reservation`.

- [ ] **Step 4: Run the scoping tests**

Run: `uv run pytest tests/unit/test_shared_store_scoping.py tests/unit/test_shared_store.py -v`
Expected: PASS. If SQLite rejects `LIMIT :n`, wrap with `int(...)` before binding (SQLite accepts bound integers for LIMIT).

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_store.py tests/unit/test_shared_store_scoping.py
git commit -m "feat(seller-shared): org-scoped store covers orders, inventory, settlement, evidence"
```

---

### Task 3: Org-scoped agreement review store

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_review_store.py`
- Test: `tests/unit/test_shared_review_store.py`

**Interfaces:**
- Produces: `OrgScopedAgreementReviewStore(engine, organization_id)` with `record`, `get`, `list` matching `SellerAgreementReviewStore`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_review_store.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from seller_agent.shared_review_store import OrgScopedAgreementReviewStore
from seller_agent.shared_schema import create_shared_schema


class Projection:
    agreement_id = "agr-1"
    agreement_version = 1
    agreement_hash = "ah"
    terms = {"total": 100}
    change_request_id = None


@pytest.mark.asyncio
async def test_reviews_are_org_scoped(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await create_shared_schema(engine)
    a = OrgScopedAgreementReviewStore(engine, "org-a")
    b = OrgScopedAgreementReviewStore(engine, "org-b")
    a.record(Projection(), "oh", decision="accepted", now="2026-01-01T00:00:00Z",
             task_id="t", context_id="c")
    assert a.get("agr-1", 1)["decision"] == "accepted"
    assert b.get("agr-1", 1) is None
    await engine.dispose()
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_shared_review_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement it**

```python
# apps/seller_agent/seller_agent/shared_review_store.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class OrgScopedAgreementReviewStore:
    def __init__(self, db_path: Path | str, organization_id: str) -> None:
        self.db_path = Path(db_path)
        self.organization_id = organization_id

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def record(self, projection, offer_hash, *, decision, now, task_id, context_id):
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO seller_agreement_reviews
                   (organization_id, agreement_id, version, agreement_hash,
                    offer_hash, terms, change_request_id, decision, reviewed_at,
                    task_id, context_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (self.organization_id, projection.agreement_id,
                 projection.agreement_version, projection.agreement_hash,
                 offer_hash, json.dumps(projection.terms, sort_keys=True),
                 projection.change_request_id, decision,
                 now.isoformat().replace("+00:00", "Z")
                 if hasattr(now, "isoformat") else str(now),
                 task_id, context_id))

    def get(self, agreement_id, version):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM seller_agreement_reviews "
                "WHERE organization_id=? AND agreement_id=? AND version=?",
                (self.organization_id, agreement_id, version)).fetchone()
        return dict(row) if row else None

    def list(self, agreement_id):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM seller_agreement_reviews "
                "WHERE organization_id=? AND agreement_id=? ORDER BY version",
                (self.organization_id, agreement_id)).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_shared_review_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_review_store.py tests/unit/test_shared_review_store.py
git commit -m "feat(seller-shared): org-scoped agreement review store"
```

---

### Task 4: Tenant-aware cards, graph checkpoints, and service scope

**Files:**
- Modify: `apps/seller_agent/seller_agent/card.py`
- Modify: `apps/seller_agent/seller_agent/graph.py`
- Modify: `apps/seller_agent/seller_agent/service.py`
- Test: `tests/unit/test_shared_card_and_graph.py`

**Interfaces:**
- Produces: `build_agent_card(policy, base_url, tenant: str | None = None)`.
- Produces: `build_graph(checkpointer=None)`.
- Produces: `SellerService(..., graph=None, scope: str = "")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shared_card_and_graph.py
from commerce_core.pricing import load_policy
from seller_agent.card import build_agent_card
from seller_agent.graph import build_graph


def test_card_advertises_shared_url_and_tenant():
    policy = load_policy("apps/seller_agent/seller_agent/profiles/northwind.yaml")
    card = build_agent_card(policy, "http://127.0.0.1:9200", tenant="agent_northwind-audio")
    interface = card.supported_interfaces[0]
    assert interface.url == "http://127.0.0.1:9200/a2a"
    assert interface.tenant == "agent_northwind-audio"


def test_graph_accepts_an_injected_checkpointer(tmp_path):
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_graph(checkpointer=MemorySaver())
    assert graph is not None
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_shared_card_and_graph.py -v`
Expected: FAIL (`build_agent_card` got an unexpected keyword argument `tenant`).

- [ ] **Step 3: Implement**

In `card.py`, change the signature and interface:

```python
def build_agent_card(policy: SellerPolicy, base_url: str, tenant: str | None = None) -> AgentCard:
    ...
    AgentInterface(
        url=f"{base_url}/a2a",
        protocol_binding=TransportProtocol.JSONRPC.value,
        protocol_version=PROTOCOL_VERSION_CURRENT,
        tenant=tenant or "",
    )
```

Callers pass the seller-specific URL, so the shared app passes `base_url=f"{settings.public_base_url}/{seller_id}"`.

In `graph.py`:

```python
def build_graph(checkpointer=None):
    ...
    return builder.compile(checkpointer=checkpointer or MemorySaver())
```

In `service.py`, change `__init__` to accept `graph=None, scope: str = ""` and use them:

```python
        self.graph = graph or build_graph()
        self.scope = scope
```

In `handle_turn`, change the thread id:

```python
            "thread_id": f"{self.scope}:{task_id}" if self.scope else task_id,
```

- [ ] **Step 4: Run the tests and the existing service tests**

Run: `uv run pytest tests/unit/test_shared_card_and_graph.py tests/unit/test_seller_service.py -q`
Expected: PASS (or the existing service test file name if different; run `uv run pytest tests/unit -q`).

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/card.py apps/seller_agent/seller_agent/graph.py apps/seller_agent/seller_agent/service.py tests/unit/test_shared_card_and_graph.py
git commit -m "feat(seller-shared): tenant cards, injectable graph, scoped checkpoints"
```

---

### Task 5: Credential verification and shared call context

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_auth.py`
- Test: `tests/unit/test_shared_auth.py`

**Interfaces:**
- Produces: `ControlPlaneCredentialVerifier(base_url, ttl_seconds=30, client=None)` with `async verify(token, purpose="a2a:call") -> dict | None`.
- Produces: `StaticDemoCredentialVerifier(path)` with the same method.
- Produces: `SharedAuthMiddleware(app, verifier)`.
- Produces: `SharedCallContextBuilder` with `build(request) -> ServerCallContext`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_auth.py
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from seller_agent.shared_auth import SharedAuthMiddleware


class Verifier:
    async def verify(self, token, purpose="a2a:call"):
        return {"organization_id": "org-a", "agent_id": "agent-a",
                "status": "active", "scopes": ["a2a:call"]} if token == "good" else None


def test_a2a_requires_a_valid_bearer():
    app = FastAPI()
    app.add_middleware(SharedAuthMiddleware, verifier=Verifier())

    @app.post("/shop/a2a")
    async def a2a():
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/shop/a2a").status_code == 401
    assert client.post("/shop/a2a", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.post("/shop/a2a", headers={"Authorization": "Bearer good"}).status_code == 200
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_shared_auth.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `shared_auth.py`**

```python
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from a2a.server.context import ServerCallContext
from a2a.server.routes.common import ServerCallContextBuilder


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    prefix = "bearer "
    return header[len(prefix):].strip() if header.lower().startswith(prefix) else ""


class ControlPlaneCredentialVerifier:
    def __init__(self, base_url: str, *, ttl_seconds: float = 30.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._cache: dict[str, tuple[float, dict]] = {}

    async def verify(self, token: str, purpose: str = "a2a:call") -> dict | None:
        if not token:
            return None
        key = _hash(token)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        client = self._client or httpx.AsyncClient(timeout=5.0)
        try:
            response = await client.post(
                f"{self.base_url}/v1/agent-credentials/verify",
                json={"token": token, "purpose": purpose})
        except httpx.HTTPError:
            return None
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("status") != "active":
            return None
        self._cache[key] = (now + self.ttl_seconds, data)
        return data


class StaticDemoCredentialVerifier:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    async def verify(self, token: str, purpose: str = "a2a:call") -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        caller = data.get("tokens", {}).get(_hash(token))
        return caller if caller and caller.get("status") == "active" else None


class SharedAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, verifier) -> None:
        super().__init__(app)
        self.verifier = verifier

    async def dispatch(self, request: Request, call_next):
        if request.url.path.endswith("/a2a"):
            caller = await self.verifier.verify(_bearer(request))
            if caller is None:
                return JSONResponse(
                    {"error": "unauthorized", "detail": "invalid credential"},
                    status_code=401)
            request.state.caller = caller
        return await call_next(request)


class SharedCallContextBuilder(ServerCallContextBuilder):
    def build(self, request: Request) -> ServerCallContext:
        context = ServerCallContext()
        context.state["seller_id"] = request.path_params.get("seller_id", "")
        context.state["caller"] = getattr(request.state, "caller", None)
        return context
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_shared_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_auth.py tests/unit/test_shared_auth.py
git commit -m "feat(seller-shared): control-plane credential verification and auth middleware"
```

---

### Task 6: Tenant resolver and routing executor

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_runtime.py`
- Test: `tests/integration/test_shared_tenant_resolution.py`

**Interfaces:**
- Produces: `TenantContext(agent_id, organization_id, seller_id, config)`.
- Produces: `TenantResolver(engine)` with `async resolve(tenant, path_seller_id=None) -> TenantContext`.
- Produces: `TenantRoutingExecutor(resolver, runtime)` implementing `AgentExecutor`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_shared_tenant_resolution.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_runtime import TenantForbidden, TenantResolver, UnknownTenant
from seller_agent.shared_schema import create_shared_schema


@pytest.mark.asyncio
async def test_tenant_resolution_enforces_path(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await create_shared_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(
            """INSERT INTO seller_configs
               (agent_id, organization_id, seller_id, name, status)
               VALUES ('agent_a', 'org-a', 'seller-a', 'Seller A', 'active')"""))
    resolver = TenantResolver(engine)
    ctx = await resolver.resolve("agent_a", path_seller_id="seller-a")
    assert ctx.organization_id == "org-a"
    with pytest.raises(TenantForbidden):
        await resolver.resolve("agent_a", path_seller_id="seller-b")
    with pytest.raises(UnknownTenant):
        await resolver.resolve("agent_missing", path_seller_id="seller-a")
    await engine.dispose()
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/integration/test_shared_tenant_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `shared_runtime.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from seller_agent.shared_store import ConfigSnapshot


class UnknownTenant(Exception):
    pass


class TenantForbidden(Exception):
    pass


@dataclass(frozen=True)
class TenantContext:
    agent_id: str
    organization_id: str
    seller_id: str
    config: ConfigSnapshot


class TenantResolver:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def resolve(self, tenant: str, path_seller_id: str | None = None) -> TenantContext:
        agent_id = (tenant or "").strip()
        if not agent_id:
            if not path_seller_id:
                raise UnknownTenant("tenant is required")
            agent_id = f"agent_{path_seller_id}"
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT * FROM seller_configs WHERE agent_id=:a"),
                {"a": agent_id})).first()
        if row is None or row.status != "active":
            raise UnknownTenant(agent_id)
        if path_seller_id and row.seller_id != path_seller_id:
            raise TenantForbidden(
                f"path {path_seller_id!r} does not match tenant {row.seller_id!r}")
        from seller_agent.shared_store import _snapshot
        return TenantContext(
            agent_id=row.agent_id, organization_id=row.organization_id,
            seller_id=row.seller_id, config=_snapshot(row))


class TenantRoutingExecutor(AgentExecutor):
    def __init__(self, resolver: TenantResolver, runtime) -> None:
        self.resolver = resolver
        self.runtime = runtime

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        seller_ctx, service = await self._service(context)
        await service.store.record_task_ownership(context.task_id, context.context_id)
        from seller_agent.executor import SellerExecutor
        await SellerExecutor(service).execute(context, event_queue)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        seller_ctx, service = await self._service(context)
        from seller_agent.executor import SellerExecutor
        await SellerExecutor(service).cancel(context, event_queue)

    async def _service(self, context: RequestContext):
        from a2a.utils.errors import InvalidParamsError, TaskNotFoundError
        try:
            seller_ctx = await self.resolver.resolve(
                context.tenant,
                path_seller_id=context.call_context.state.get("seller_id") or None)
        except UnknownTenant as exc:
            raise TaskNotFoundError(f"unknown seller agent: {exc}") from exc
        except TenantForbidden as exc:
            raise InvalidParamsError(str(exc)) from exc
        caller = context.call_context.state.get("caller") or {}
        if caller.get("organization_id") == seller_ctx.organization_id:
            raise InvalidParamsError("caller and recipient must differ")
        service = await self.runtime.service_for(seller_ctx)
        return seller_ctx, service
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/integration/test_shared_tenant_resolution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_runtime.py tests/integration/test_shared_tenant_resolution.py
git commit -m "feat(seller-shared): tenant resolver and routing executor"
```

---

### Task 7: Shared app routes, lifespan, task store, sweeper

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_app.py`
- Create: `apps/seller_agent/seller_agent/shared_sweeper.py`
- Modify: `apps/seller_agent/seller_agent/server.py`
- Test: `tests/integration/test_shared_a2a_endpoint.py`

**Interfaces:**
- Produces: `create_shared_app(settings)`.
- Produces: `SharedRuntime(engine, settings, graph, settlement)` with `async service_for(TenantContext) -> SellerService`.

- [ ] **Step 1: Write the failing endpoint test**

```python
# tests/integration/test_shared_a2a_endpoint.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.settings import Settings
from seller_agent.shared_app import create_shared_app


class Verifier:
    async def verify(self, token, purpose="a2a:call"):
        return {"organization_id": "org-buyer", "agent_id": "agent_buyer",
                "status": "active", "scopes": ["a2a:call"]} if token == "buyer" else None


@pytest.fixture
def client(tmp_path):
    db = f"sqlite+aiosqlite:///{tmp_path}/sellers.db"
    settings = Settings(config_source="shared", shared_db_url=db,
                        public_base_url="http://testserver")
    app = create_shared_app(settings, credential_verifier=Verifier())
    with TestClient(app) as c:
        c.app.state.engine.begin()
        yield c


def test_card_and_a2a_share_one_host(client):
    card = client.get("/seller-a/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json()["supportedInterfaces"][0]["tenant"] == "agent_seller-a"
    response = client.post(
        "/seller-a/a2a",
        headers={"Authorization": "Bearer buyer",
                 "A2A-Version": "1.0"},
        json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
              "params": {"tenant": "agent_seller-a",
                         "message": {"messageId": "m1", "role": 1,
                                     "parts": [{"text": "hello"}]}}})
    assert response.status_code == 200
    assert "error" not in response.json() or response.json()["error"]["code"] != -32001
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/integration/test_shared_a2a_endpoint.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `shared_app.py`**

The module must:

```python
def create_shared_app(settings, *, credential_verifier=None):
    engine = create_async_engine(settings.shared_db_url)
    if credential_verifier is None and settings.verifund_mode == "off":
        credential_verifier = StaticDemoCredentialVerifier(settings.demo_credentials_path)
    elif credential_verifier is None:
        credential_verifier = ControlPlaneCredentialVerifier(settings.verifund_url)
    ...
    @asynccontextmanager
    async def lifespan(app):
        await configure_shared_engine(engine)
        await create_shared_schema(engine)
        app.state.shared_engine = engine
        app.state.settings = settings
        app.state.credential_verifier = credential_verifier
        task_store = DatabaseTaskStore(
            engine=engine, create_table=True,
            owner_resolver=lambda ctx: (ctx.state.get("caller") or {}).get("organization_id", ""))
        checkpointer_cm = AsyncSqliteSaver.from_conn_string(settings.checkpoint_path)
        checkpointer = await checkpointer_cm.__aenter__()
        graph = build_graph(checkpointer=checkpointer)
        settlement = SellerSettlementClient(settings.verifund_url) if settings.verifund_mode != "off" else None
        runtime = SharedRuntime(engine, settings, graph, settlement)
        resolver = TenantResolver(engine)
        handler = DefaultRequestHandler(
            agent_executor=TenantRoutingExecutor(resolver, runtime),
            task_store=task_store, agent_card=build_agent_card(...))
        app.state.handler = handler
        sweeper = SharedEvidenceSweeper(engine, settings, settlement)
        await sweeper.start()
        yield
        await sweeper.stop()
        if settlement: await settlement.close()
        await checkpointer_cm.__aexit__(None, None, None)
        await engine.dispose()
```

Routes:

```python
    app = FastAPI(title="seller-shared", lifespan=lifespan)
    app.add_middleware(SharedAuthMiddleware, verifier=credential_verifier)
    app.include_router(internal_router)

    @app.get("/health")
    async def health(): return {"status": "ok"}

    @app.get("/{seller_id}/.well-known/agent-card.json")
    async def card(seller_id: str):
        row = await _active_config(engine, seller_id)
        if row is None: raise HTTPException(404)
        policy = await OrgScopedStore(engine, organization_id=row.organization_id,
                                      agent_id=row.agent_id).load_policy()
        return JSONResponse(agent_card_to_dict(build_agent_card(
            policy, f"{settings.public_base_url}/{seller_id}", tenant=row.agent_id)))

    @app.get("/{seller_id}/api/catalog")
    async def catalog(seller_id: str): ...  # same shape as current public catalog

    @app.get("/{seller_id}/api/console/dashboard")
    async def dashboard(seller_id: str, request: Request):
        _require_internal_token(request)
        ...  # use build_console_dashboard(store, policy, service)

    # A2A JSON-RPC routes: one path param route, not one route per seller
    dispatcher = JsonRpcDispatcher(handler, context_builder=SharedCallContextBuilder(),
                                   enable_v0_3_compat=True)
    app.router.routes.append(Route("/{seller_id}/a2a", dispatcher.handle_requests, methods=["POST"]))
    app.router.routes.append(Route("/a2a", dispatcher.handle_requests, methods=["POST"]))
```

`SharedRuntime.service_for` constructs an `OrgScopedStore`, loads policy/mandate, and returns a `SellerService` with `graph=self.graph`, `scope=f"organization_id:{ctx.organization_id}:{ctx.agent_id}"`, `review_store=OrgScopedAgreementReviewStore(...)`, and the shared settlement client. It must not construct an `EvidenceOutbox` per request; evidence is written directly through the store by `SellerService` (see `service.py` lines 163–196).

`shared_sweeper.py`:

```python
class SharedEvidenceSweeper:
    def __init__(self, engine, settings, settlement, interval=2.0):
        ...
    async def start(self):
        self._task = asyncio.create_task(self._loop())
    async def _loop(self):
        while not self._stop.is_set():
            async with self.engine.connect() as conn:
                rows = (await conn.execute(text(
                    "SELECT agent_id, organization_id FROM seller_configs WHERE status='active'"
                ))).all()
            for row in rows:
                store = OrgScopedStore(self.engine, organization_id=row.organization_id,
                                       agent_id=row.agent_id)
                await EvidenceOutbox(store, self.settlement).run_once()
            await asyncio.sleep(self.interval)
```

- [ ] **Step 4: Run the endpoint test**

Run: `uv run pytest tests/integration/test_shared_a2a_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Route `server.create_app` to it**

In `server.py`:

```python
    if settings.config_source == "shared":
        from seller_agent.shared_app import create_shared_app
        return create_shared_app(settings)
```

Delete `_create_shared_app` and its imports.

- [ ] **Step 6: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_app.py apps/seller_agent/seller_agent/shared_sweeper.py apps/seller_agent/seller_agent/server.py tests/integration/test_shared_a2a_endpoint.py
git commit -m "feat(seller-shared): single-host A2A routes, task store, and evidence sweeper"
```

---

### Task 8: Control-plane demo agents and credentials

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py`
- Test: `tests/unit/test_seed_demo_agents.py`

**Interfaces:**
- Produces: `async seed_demo_agents(store, settings)`; creates seller agents `agent_<seller_id>` (`active`), buyer org/agent `agent_marketmesh_buyer` (`active`), seller `a2a:test` credentials from `SELLER_*_TOKEN`, and buyer `a2a:call` credential from `BUYER_AGENT_TOKEN`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_seed_demo_agents.py
import hashlib
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.tenancy.repository import TenancyRepository
from verifund_control_plane.tenancy.backfill import seed_demo_agents


class Settings:
    seller_tokens = {"northwind-audio": "dev-northwind"}
    buyer_agent_token = "dev-buyer-agent"


@pytest.mark.asyncio
async def test_seed_demo_agents(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    store = TenancyRepository(engine)
    await store.create_schema()
    await seed_demo_agents(store, Settings())
    agent = await store.get_agent("agent_northwind-audio")
    assert agent["status"] == "active"
    row = await store.get_credential_by_hash(
        hashlib.sha256(b"dev-buyer-agent").hexdigest())
    assert row["agent_id"] == "agent_marketmesh_buyer"
    await engine.dispose()
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_seed_demo_agents.py -v`
Expected: FAIL with `ImportError` for `seed_demo_agents`.

- [ ] **Step 3: Implement**

```python
import hashlib

async def seed_demo_agents(store, settings) -> None:
    from verifund_control_plane.agents.credentials import verify_credential  # noqa: F401
    buyer_org = await store.ensure_seed_buyer_organization("marketmesh-buyer")
    buyer = await store.get_agent("agent_marketmesh_buyer")
    if buyer is None:
        await store.create_agent(
            organization_id=buyer_org["id"], name="MarketMesh Buyer",
            created_by="seed", policy_ref="buyer/v1", policy_version="1",
            policy_hash="0" * 64, agent_id="agent_marketmesh_buyer")
    await store.set_agent_status("agent_marketmesh_buyer", "active")
    buyer_token = settings.buyer_agent_token
    if await store.get_credential_by_hash(hashlib.sha256(buyer_token.encode()).hexdigest()) is None:
        await store.create_credential(
            buyer_org["id"], "agent_marketmesh_buyer",
            hashlib.sha256(buyer_token.encode()).hexdigest(), ["a2a:call"])

    for seller_id, token in settings.seller_tokens.items():
        org = await store.ensure_seed_organization(
            seller_id=seller_id, kind="business", verified=True)
        agent_id = f"agent_{seller_id}"
        if await store.get_agent(agent_id) is None:
            await store.create_agent(
                organization_id=org["id"], name=seller_id, created_by="seed",
                policy_ref=f"{seller_id}/v1", policy_version="1",
                policy_hash="0" * 64, agent_id=agent_id)
        await store.set_agent_status(agent_id, "active")
        digest = hashlib.sha256(token.encode()).hexdigest()
        if await store.get_credential_by_hash(digest) is None:
            await store.create_credential(org["id"], agent_id, digest, ["a2a:test"])
```

Call `await seed_demo_agents(app.state.tenancy, settings)` right after `seed_payment_accounts(...)` in `app.py`.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_seed_demo_agents.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_seed_demo_agents.py
git commit -m "feat(control-plane): seed demo seller and buyer agent credentials"
```

---

### Task 9: Seed `sellers.db` from the YAML profiles

**Files:**
- Create: `scripts/seed_shared.py`
- Modify: `scripts/seed.py`
- Test: `tests/unit/test_seed_shared.py`

**Interfaces:**
- Produces: `async seed_shared(config_module) -> None`; populates `seller_configs`, `products`, `inventory` for every `SELLERS` entry.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_seed_shared.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import create_shared_schema
from scripts.seed_shared import seed_seller_rows


@pytest.mark.asyncio
async def test_seed_seller_rows(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await create_shared_schema(engine)
    await seed_seller_rows(
        engine, seller_id="northwind-audio", agent_id="agent_northwind-audio",
        organization_id="org-northwind",
        profile_path="apps/seller_agent/seller_agent/profiles/northwind.yaml")
    async with engine.connect() as conn:
        config = (await conn.execute(text(
            "SELECT seller_id, status FROM seller_configs WHERE agent_id='agent_northwind-audio'"
        ))).first()
        count = (await conn.execute(text(
            "SELECT COUNT(*) FROM products WHERE organization_id='org-northwind'"
        ))).scalar_one()
    assert config.seller_id == "northwind-audio"
    assert config.status == "active"
    assert count == 10
    await engine.dispose()
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_seed_shared.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `scripts/seed_shared.py`**

```python
async def seed_seller_rows(engine, *, seller_id, agent_id, organization_id,
                           profile_path) -> None:
    from commerce_core.pricing import load_policy
    from seller_agent.card import build_agent_card
    from seller_agent.shared_store import OrgScopedStore, canonical_json_bytes, sha256_hex
    policy = load_policy(profile_path)
    store = OrgScopedStore(engine, organization_id=organization_id, agent_id=agent_id)
    await store.import_products([p.model_dump(mode="json") for p in policy.catalog()],
                                replace=True)
    card = build_agent_card(policy, "http://127.0.0.1:9200")
    card_hash = sha256_hex(canonical_json_bytes(AgentCardToDict(card)))
    policy_hash = sha256_hex(canonical_json_bytes({
        "seller_id": seller_id, "name": policy.name,
        "tagline": policy.tagline, "categories": policy.categories,
        "products": [p.model_dump(mode="json") for p in policy.catalog()],
    }))
    tools = ["commerce.catalog.search", "commerce.quote", "commerce.negotiate",
             "commerce.order", "commerce.agreement.review"]
    async with engine.begin() as conn:
        await conn.execute(text(
            """INSERT INTO seller_configs
                 (agent_id, organization_id, seller_id, name, tagline, instructions,
                  max_discount_bps, autonomy_mode, tool_allowlist_json, policy_version,
                  policy_hash, card_hash, config_version, status)
               VALUES (:a, :o, :s, :n, :t, :ins, 1000, 'policy_bounded', :tools,
                       1, :ph, :ch, 1, 'active')
               ON CONFLICT(agent_id) DO UPDATE SET
                 organization_id=:o, seller_id=:s, name=:n, tagline=:t,
                 instructions=:ins, tool_allowlist_json=:tools,
                 policy_hash=:ph, card_hash=:ch, status='active'"""),
            {"a": agent_id, "o": organization_id, "s": seller_id,
             "n": policy.name, "t": policy.tagline, "ins": "",
             "tools": json.dumps(tools), "ph": policy_hash, "ch": card_hash})
```

`seed.py` becomes:

```python
async def main():
    engine = create_async_engine(shared_db_url())
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    orgs = await seed_control_plane_orgs_and_agents()
    for seller in SELLERS:
        await seed_seller_rows(
            engine, seller_id=seller.seller_id,
            agent_id=f"agent_{seller.seller_id}",
            organization_id=orgs[seller.seller_id],
            profile_path=seller.profile_path)
        register_seller(client, seller,
                        card_url=f"{shared_seller_base_url()}/{seller.seller_id}/.well-known/agent-card.json")
    write_demo_credentials(...)
    await engine.dispose()
```

`seed_control_plane_orgs_and_agents()` opens `verifund_database_url()`, creates the repo, calls `ensure_seed_organization`/`ensure_seed_buyer_organization`, `seed_demo_agents`, and returns `{seller_id: org_id}`.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_seed_shared.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_shared.py scripts/seed.py tests/unit/test_seed_shared.py
git commit -m "feat(seed): populate shared sellers.db and demo agents"
```

---

### Task 10: One shared process in the dev stack

**Files:**
- Modify: `scripts/config.py`
- Modify: `scripts/dev.py`
- Modify: `.env`, `.env.example`, `docker-compose.yml`
- Test: `tests/unit/test_verifund_dev_config.py`

**Interfaces:**
- Produces: `config.shared_seller_port()`, `config.shared_seller_url()`, `config.shared_seller_db_url()`, `config.seller_internal_token()`, `config.buyer_agent_token()`, `config.seller_checkpoint_path()`.
- Produces: `dev.shared_seller_environment(mode)`.

- [ ] **Step 1: Write the failing test**

```python
def test_shared_seller_environment(monkeypatch):
    monkeypatch.setenv("SELLER_SHARED_PORT", "9200")
    env = dev.shared_seller_environment("scripted")
    assert env["PORT"] == "9200"
    assert env["SELLER_CONFIG_SOURCE"] == "shared"
    assert env["SELLER_SHARED_DB_URL"].endswith("sellers.db")
    assert env["PUBLIC_BASE_URL"] == "http://127.0.0.1:9200"
    assert env["SELLER_INTERNAL_TOKEN"] == "dev-seller-internal"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py::test_shared_seller_environment -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement config and dev**

In `scripts/config.py`:

```python
def shared_seller_port() -> int:
    return _port("SELLER_SHARED_PORT", 9200)

def shared_seller_url() -> str:
    return _env("SELLER_SHARED_URL", f"http://127.0.0.1:{shared_seller_port()}").rstrip("/")

def shared_seller_db_url() -> str:
    return _env("SELLER_SHARED_DB_URL", "sqlite+aiosqlite:///./data/sellers.db")

def seller_internal_token() -> str:
    return _env("SELLER_INTERNAL_TOKEN", "dev-seller-internal")

def buyer_agent_token() -> str:
    return _env("BUYER_AGENT_TOKEN", "dev-buyer-agent")

def seller_checkpoint_path() -> str:
    return _env("SELLER_CHECKPOINT_PATH", "./data/seller-checkpoints.sqlite")

def shared_card_url(seller_id: str) -> str:
    return f"{shared_seller_url()}/{seller_id}/.well-known/agent-card.json"
```

Add `shared_seller_environment(mode)` to `dev.py`:

```python
def shared_seller_environment(mode: str, verifund_mode: str = "sandbox") -> dict[str, str]:
    env = _base_env(mode)
    env.update({
        "HOST": _env_value("HOST", "127.0.0.1"),
        "PORT": str(shared_seller_port()),
        "SELLER_PORT": str(shared_seller_port()),
        "SELLER_CONFIG_SOURCE": "shared",
        "SELLER_SHARED_DB_URL": shared_seller_db_url(),
        "SELLER_INTERNAL_TOKEN": seller_internal_token(),
        "PUBLIC_BASE_URL": shared_seller_url(),
        "SELLER_CHECKPOINT_PATH": seller_checkpoint_path(),
        "VERIFUND_MODE": verifund_mode,
        "BUYER_AGENT_TOKEN": buyer_agent_token(),
    })
    if verifund_mode != "off":
        env["VERIFUND_URL"] = config.verifund_url()
    return env
```

In `run_stack`, replace the seller loop with:

```python
        shared = start_child(
            "seller-shared",
            [sys.executable, "-m", "seller_agent"],
            env=shared_seller_environment(mode, settlement_mode),
            url=f"{shared_seller_url()}/health",
        )
        children.append(shared)
        wait_for_http("seller-shared", f"{shared_seller_url()}/health",
                      timeout=45, process=shared.process, log_path=shared.log_path)
```

Update `allowed_card_urls_json()` and `seller_auth_environment()`:

```python
def allowed_card_urls_json() -> str:
    urls = {shared_card_url(s.seller_id) for s in SELLERS}
    ...
```

Keep `seller_auth_environment()` for the control-plane test credentials and console env.

Update the readiness banner to print `Shared seller  {shared_seller_url()}` once.

In `.env` and `.env.example`:

```dotenv
SELLER_SHARED_PORT=9200
SELLER_SHARED_URL=http://127.0.0.1:9200
SELLER_SHARED_DB_URL=sqlite+aiosqlite:///./data/sellers.db
SELLER_INTERNAL_TOKEN=dev-seller-internal
SELLER_CHECKPOINT_PATH=./data/seller-checkpoints.sqlite
BUYER_AGENT_TOKEN=dev-buyer-agent
```

In `docker-compose.yml`, replace the four seller services with one:

```yaml
  seller-shared:
    build: { context: ., dockerfile: Dockerfile.python }
    command: python -m seller_agent
    environment:
      PORT: 9200
      SELLER_CONFIG_SOURCE: shared
      SELLER_SHARED_DB_URL: sqlite+aiosqlite:////app/data/sellers.db
      SELLER_INTERNAL_TOKEN: ${SELLER_INTERNAL_TOKEN:-dev-seller-internal}
      PUBLIC_BASE_URL: ${SELLER_SHARED_URL:-http://127.0.0.1:9200}
      VERIFUND_MODE: ${VERIFUND_MODE:-sandbox}
      VERIFUND_URL: http://verifund:9300
    ports: ["9200:9200"]
    volumes: ["marketmesh-data:/app/data"]
```

- [ ] **Step 4: Run the config tests**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py -v`
Expected: PASS after updating the old per-seller assertions.

- [ ] **Step 5: Commit**

```bash
git add scripts/config.py scripts/dev.py .env .env.example docker-compose.yml tests/unit/test_verifund_dev_config.py
git commit -m "feat(dev): run one shared seller endpoint on port 9200"
```

---

### Task 11: Discovery URL derivation and buyer credential

**Files:**
- Modify: `apps/registry/registry/api.py`
- Modify: `apps/buyer_agent/buyer_agent/registry_client.py`
- Modify: `apps/buyer_agent/buyer_agent/settings.py`
- Test: `tests/unit/test_shared_url_derivation.py`

**Interfaces:**
- Produces: `seller_path_base(card_url) -> str` (e.g. `http://host:9200/seller-a`).
- Produces: buyer setting `seller_internal_token` and `buyer_agent_token`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_url_derivation.py
from registry.api import seller_catalog_url
from buyer_agent.registry_client import seller_catalog_url as buyer_catalog_url


def test_catalog_url_preserves_seller_prefix():
    card = "http://127.0.0.1:9200/northwind-audio/.well-known/agent-card.json"
    expected = "http://127.0.0.1:9200/northwind-audio/api/catalog"
    assert seller_catalog_url(card) == expected
    assert buyer_catalog_url(card) == expected


def test_file_mode_card_still_maps_to_root_catalog():
    card = "http://127.0.0.1:9201/.well-known/agent-card.json"
    assert seller_catalog_url(card) == "http://127.0.0.1:9201/api/catalog"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/unit/test_shared_url_derivation.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the helper in both modules**

```python
def seller_path_base(card_url: str) -> str:
    url = httpx.URL(card_url)
    suffix = "/.well-known/agent-card.json"
    path = url.path
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return str(url.copy_with(path=path or "/", query=None, fragment=None)).rstrip("/")


def seller_catalog_url(card_url: str) -> str:
    return f"{seller_path_base(card_url)}/api/catalog"


def seller_dashboard_url(card_url: str) -> str:
    return f"{seller_path_base(card_url)}/api/console/dashboard"
```

Use `seller_catalog_url` in registry `_fetch_catalog` and buyer `refresh_seller_catalog`; use `seller_dashboard_url` in `fetch_seller_dashboard`.

In buyer `settings.py`:

```python
    seller_internal_token: str = Field(
        default="dev-seller-internal",
        validation_alias=AliasChoices("SELLER_INTERNAL_TOKEN"))
    buyer_agent_token: str = Field(
        default="dev-buyer-agent",
        validation_alias=AliasChoices("BUYER_AGENT_TOKEN"))
```

In `fetch_seller_dashboard`, replace the bearer header with `{"X-Internal-Token": self.seller_internal_token}`. In `refresh_seller_catalog`, drop the Authorization header.

In `dev.buyer_environment`, add:

```python
            "SELLER_INTERNAL_TOKEN": seller_internal_token(),
            "BUYER_AGENT_TOKEN": buyer_agent_token(),
```

and set `BUYER_SELLER_TOKENS` to map every seller to `buyer_agent_token()` instead of per-seller tokens.

- [ ] **Step 4: Run the URL tests and registry/buyer tests**

Run: `uv run pytest tests/unit/test_shared_url_derivation.py tests/unit/test_registry_projection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/registry/registry/api.py apps/buyer_agent/buyer_agent/registry_client.py apps/buyer_agent/buyer_agent/settings.py scripts/dev.py tests/unit/test_shared_url_derivation.py
git commit -m "feat(discovery): preserve seller path prefix and use buyer agent credential"
```

---

### Task 12: Cross-tenant negative tests, smoke, and docs

**Files:**
- Modify: `tests/integration/test_shared_a2a_endpoint.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md` (status note only)

**Interfaces:**
- Consumes: all previous tasks.

- [ ] **Step 1: Add negative tests**

Append to `tests/integration/test_shared_a2a_endpoint.py`:

```python
def test_unknown_tenant_is_404(client):
    response = client.post(
        "/seller-a/a2a",
        headers={"Authorization": "Bearer buyer", "A2A-Version": "1.0"},
        json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
              "params": {"tenant": "agent_missing",
                         "message": {"messageId": "m1", "role": 1,
                                     "parts": [{"text": "hello"}]}}})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32001


def test_path_tenant_mismatch_is_403(client):
    response = client.post(
        "/seller-b/a2a",
        headers={"Authorization": "Bearer buyer", "A2A-Version": "1.0"},
        json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
              "params": {"tenant": "agent_seller-a",
                         "message": {"messageId": "m1", "role": 1,
                                     "parts": [{"text": "hello"}]}}})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


def test_missing_credential_is_401(client):
    response = client.post(
        "/seller-a/a2a",
        headers={"A2A-Version": "1.0"},
        json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {}})
    assert response.status_code == 401
```

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 3: Update the docs**

In `README.md`, replace the four seller URLs in the run instructions with:

```markdown
  Shared seller  http://127.0.0.1:9200
```

Add a short note: discovery cards live at `/{seller_id}/.well-known/agent-card.json`, A2A at `/{seller_id}/a2a`, and the `tenant` is `agent_<seller_id>`.

In the design spec header, change `Status: Design for approval.` to `Status: Implemented by docs/superpowers/plans/2026-11-07-single-shared-a2a-cutover.md.`

- [ ] **Step 4: Smoke the local stack**

Run: `make reset && make dev`
Expected: one `seller-shared` process; seed prints four sellers; console reachable; registry lists four sellers all pointing at `http://127.0.0.1:9200/{seller_id}/.well-known/agent-card.json`.

Then in another shell:

```bash
curl -s http://127.0.0.1:9200/northwind-audio/.well-known/agent-card.json | jq '.supportedInterfaces[0]'
curl -s http://127.0.0.1:9105/v1/sellers | jq '.[].card_url'
```

Expected: tenant `agent_northwind-audio`; every card URL shares port 9200.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_shared_a2a_endpoint.py README.md docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md
git commit -m "test(shared-a2a): cross-tenant negatives and cutover docs"
```

---

## Self-review notes

- Spec §3.1/§4 (routing, auth, denial) → Tasks 5–7.
- Spec §7.1–§7.6 (shared DB, scoped store, config resolution) → Tasks 1–3, 6, 9.
- Spec §7.7 (evidence sweeper) → Task 7.
- Spec §7.5 (checkpoints) → Task 4.
- Spec §8 (cards/tenant) → Tasks 4, 7.
- Spec §10 (cutover, registry flip, container retirement) → Tasks 9–11.
- Spec §12 (Neon) stays out of scope.
