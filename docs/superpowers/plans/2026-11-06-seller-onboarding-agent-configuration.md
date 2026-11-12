# Seller Onboarding — Agent Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sellers can configure, test and activate their A2A Seller Agent entirely from the seller workspace onboarding wizard after Clerk sign-in — including importing their catalog from a JSON/YAML file — with the shared Seller Agent runtime resolving configuration from `sellers.db`.

**Architecture:** Console (Next.js + Clerk) renders the wizard; every mutation goes through the Verifund control plane (FastAPI) which authenticates the Clerk session, pins the organization, and orchestrates the shared Seller Agent runtime over internal service endpoints (`/internal/*`). The seller runtime owns `sellers.db` (products, inventory, scoped config, org-bound access); the control plane owns lifecycle, credentials and the registry projection (existing `2026-11-06` decisions).

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2 async, SQLite (WAL), pydantic v2, pytest + aiosqlite, Next.js (app router) + TypeScript, Clerk (`@clerk/nextjs`), vitest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md` — especially **Appendix B** (this plan builds it), §3.4, §7 (data topology), §9 (isolation invariants), §11 (accepted risks).

## Global Constraints

- **Tenancy:** `organization_id` is the only isolation key. Every seller-data query carries it; repositories constructed without it raise; there is no code path that reads seller data without it (fail closed).
- **Naming:** agents are `agent_<slug>` unique per organization; public slug `seller_id`; control plane never trusts a client-supplied `organization_id`.
- **Denial semantics:** `404` unknown id/path · `401` bad/expired credential · `403` org/tenant mismatch or inactive recipient — per the spec's §9 rules.
- **Idempotency:** `POST /v1/agents` and `POST /v1/seller/catalog/import` honor `Idempotency-Key` header + `(organization_id, key)` replay protection via audit-event lookup.
- **Import caps:** ≤ 2 MB document, ≤ 1000 SKUs, unknown fields rejected, pricing invariant `floor ≤ initial ≤ list`, no duplicate SKUs — all violations abort with zero writes.
- **Config freshness:** seller configuration is read fresh per request; only credential verification is cached (30s, token-hash key).
- **Checkpoint:** seller graphs use `AsyncSqliteSaver` on `data/seller_checkpoints.sqlite`; `thread_id = organization_id:{org}:{agent_id}:{thread}`. (Not wired in this milestone's checks.)
- **Accepted divergences (do not "fix"):** all capability checkboxes default ON (O14); synchronous provisioning (O6); no catalog hash/drift for catalog data (O27/Q27); `replace_catalog` full replace requires an explicit flag + UI confirmation.
- **Out of scope:** profile/verification wizard steps, external integrations/OAuth sync, credential rotation, Neon/PostgreSQL, cutover of the four demo sellers, per-pair ACLs.
- All existing tests must stay green: `uv run pytest` must pass at the end.

---

## File Structure

**Created (Python):**
- `apps/seller_agent/seller_agent/shared_schema.py` — DDL for the shared `sellers.db` (fresh file, org-scoped tables, WAL pragmas)
- `apps/seller_agent/seller_agent/shared_store.py` — `OrgScopedStore` (fail-closed) + `ConfigSnapshot`/`ConfigUpsert` types
- `apps/seller_agent/seller_agent/catalog_import.py` — JSON/YAML sniff + strict validation (`ImportProduct`, `ImportResult`, `parse_catalog_document`)
- `apps/seller_agent/seller_agent/hashing.py` — canonical JSON hashing for policy/card hashes
- `apps/seller_agent/seller_agent/internal_routes.py` — `/internal/agent-configs`, `/internal/catalog/import`, `GET /internal/agent-configs/{agent_id}`, `POST /internal/test-suite`
- `tests/unit/test_shared_schema.py`, `tests/unit/test_shared_store.py`, `tests/unit/test_catalog_import.py`, `tests/unit/test_internal_routes.py`, `tests/unit/test_agent_config_routes.py` (CP endpoints)
- `tests/integration/test_onboarding_agent_flow.py` — CP orchestration of the full saga with runtime mocked via `httpx.MockTransport`
- `scripts/fixtures/example-catalog.json` and `scripts/fixtures/example-catalog.yaml` — canonical example (shared with console via copy)

**Modified (Python):**
- `apps/seller_agent/seller_agent/settings.py` — `config_source`, `shared_db_url`, `internal_api_token`
- `apps/seller_agent/seller_agent/server.py` — mount internal router when `config_source == "shared"`
- `apps/verifund_control_plane/verifund_control_plane/app.py` — nothing new if routes go into `agents/routes.py` (registered)
- `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` — new/replaced routes; see Tasks 6–8
- `apps/verifund_control_plane/verifund_control_plane/agents/lifecycle.py` — `activate_agent` extended with registry projection
- `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py` — `latest_test_run` method
- `apps/verifund_control_plane/verifund_control_plane/settings.py` — `seller_agent_url`, `seller_internal_token`, `registry_url`

**Created (Console):**
- `apps/console/lib/agent-api.ts`, `apps/console/lib/agent-types.ts`
- `apps/console/components/seller-agent/*` — `AgentIdentityPanel`, `InstructionEditor`, `CapabilityGrid`, `PolicyPanel`, `CatalogImportPanel`, `TestResultsPanel`, `AgentCardPreview`, `ActivationPanel`
- `apps/console/app/(seller-onboarding)/seller/onboarding/{integrations,agent_setup,policies,testing,activation}/page.tsx`
- `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts`
- `apps/console/app/seller/agent/page.tsx` (+ nav entry)
- `apps/console/public/example-catalog.json`, `apps/console/public/example-catalog.yaml`, `apps/console/public/example-catalog-template.yaml`
- `apps/console/tests/lib/agent-api.test.ts`, `apps/console/tests/lib/example-catalog.test.ts`

---

### Task 1: Shared `sellers.db` schema

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_schema.py`
- Test: `tests/unit/test_shared_schema.py`

**Interfaces:**
- Produces: `SHARED_DDL: list[str]`, `async def create_shared_schema(engine) -> None`, `async def configure_shared_engine(engine) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_schema.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import create_shared_schema, configure_shared_engine


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_tables_exist(engine):
    async with engine.connect() as conn:
        names = {row[0] for row in (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ))).all()}
    assert {"seller_configs", "products", "inventory", "task_ownership",
            "offers", "orders"} <= names


async def test_products_pk_is_org_scoped(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO products (organization_id, sku, name, list_unit_price_cents, "
            "initial_unit_price_cents, floor_unit_price_cents, stock_on_hand) "
            "VALUES ('orgA', 'SKU-1', 'A', 100, 90, 80, 3)"
        ))
        await conn.execute(text(
            "INSERT INTO products (organization_id, sku, name, list_unit_price_cents, "
            "initial_unit_price_cents, floor_unit_price_cents, stock_on_hand) "
            "VALUES ('orgB', 'SKU-1', 'B', 100, 90, 80, 7)"
        ))
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT organization_id, stock_on_hand FROM products"))).all()
    assert {(r[0], r[1]) for r in rows} == {("orgA", 3), ("orgB", 7)}


async def test_seller_configs_unique_seller_id(engine):
    with pytest.raises(Exception):
        async with engine.begin() as conn:
            for org in ("orgA", "orgB"):
                await conn.execute(text(
                    "INSERT INTO seller_configs (agent_id, organization_id, seller_id, name) "
                    f"VALUES ('{org}_a', '{org}', 'acme', 'Acme')"
                ))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_shared_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'seller_agent.shared_schema'`

- [ ] **Step 3: Write the implementation**

```python
# apps/seller_agent/seller_agent/shared_schema.py
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection


SHARED_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS seller_configs (
        agent_id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        seller_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        tagline TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        max_discount_bps INTEGER NOT NULL DEFAULT 1000,
        autonomy_mode TEXT NOT NULL DEFAULT 'policy_bounded',
        tool_allowlist_json TEXT NOT NULL DEFAULT '[]',
        policy_version INTEGER NOT NULL DEFAULT 1,
        policy_hash TEXT NOT NULL DEFAULT '',
        card_hash TEXT NOT NULL DEFAULT '',
        config_version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS products (
        organization_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        description TEXT NOT NULL DEFAULT '',
        list_unit_price_cents INTEGER NOT NULL CHECK (list_unit_price_cents > 0),
        original_unit_price_cents INTEGER,
        initial_unit_price_cents INTEGER NOT NULL,
        floor_unit_price_cents INTEGER NOT NULL,
        concession_ladder_json TEXT NOT NULL DEFAULT '[]',
        warranty_addons_json TEXT NOT NULL DEFAULT '{}',
        base_warranty_months INTEGER NOT NULL DEFAULT 12 CHECK (base_warranty_months >= 0),
        returns_days INTEGER NOT NULL DEFAULT 30 CHECK (returns_days >= 0),
        delivery_days INTEGER NOT NULL DEFAULT 5 CHECK (delivery_days > 0),
        stock_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (stock_on_hand >= 0),
        incoming_stock INTEGER NOT NULL DEFAULT 0 CHECK (incoming_stock >= 0),
        incoming_days INTEGER,
        image_emoji TEXT NOT NULL DEFAULT '📦',
        color TEXT NOT NULL DEFAULT '#eef2ed',
        rating REAL,
        reviews TEXT NOT NULL DEFAULT '',
        tag TEXT NOT NULL DEFAULT '',
        color_name TEXT NOT NULL DEFAULT 'black',
        sustainability_certified INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (organization_id, sku)
    )""",
    """CREATE TABLE IF NOT EXISTS inventory (
        organization_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        on_hand INTEGER NOT NULL DEFAULT 0 CHECK (on_hand >= 0),
        incoming INTEGER NOT NULL DEFAULT 0 CHECK (incoming >= 0),
        incoming_days INTEGER,
        PRIMARY KEY (organization_id, sku)
    )""",
    """CREATE TABLE IF NOT EXISTS task_ownership (
        task_id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        context_id TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS task_ownership_org ON task_ownership (organization_id)",
    """CREATE TABLE IF NOT EXISTS offers (
        organization_id TEXT NOT NULL,
        offer_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,
        offer_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        organization_id TEXT NOT NULL,
        order_id TEXT PRIMARY KEY,
        offer_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        order_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        agent_id TEXT,
        UNIQUE (organization_id, idempotency_key)
    )""",
    """CREATE TABLE IF NOT EXISTS evidence_outbox (
        organization_id TEXT NOT NULL,
        outbox_id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        agent_id TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS settlement_tokens (
        organization_id TEXT NOT NULL,
        transaction_id TEXT PRIMARY KEY,
        token_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS seller_agreement_reviews (
        organization_id TEXT NOT NULL,
        agreement_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        agreement_hash TEXT NOT NULL,
        offer_hash TEXT NOT NULL,
        terms TEXT NOT NULL,
        change_request_id TEXT,
        decision TEXT NOT NULL,
        reviewed_at TEXT NOT NULL,
        task_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        PRIMARY KEY (organization_id, agreement_id, version)
    )""",
]


async def configure_shared_engine(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")


async def create_shared_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for ddl in SHARED_DDL:
            await conn.exec_driver_sql(ddl)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_shared_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_schema.py tests/unit/test_shared_schema.py
git commit -m "feat(seller-agent): shared sellers.db schema with org-scoped tables"
```
*(Run `uv run pytest <path>` from the repo root; commands below assume repo root.)*

---

### Task 2: Org-scoped store (fail closed)

**Files:**
- Create: `apps/seller_agent/seller_agent/shared_store.py`
- Test: `tests/unit/test_shared_store.py`

**Interfaces:**
- Consumes: Task 1 `create_shared_schema`
- Produces: `TenantContextError(RuntimeError)`, `ConfigConflict(Exception) with .current_version: int`, `ConfigSnapshot` (dataclass: agent_id, organization_id, seller_id, name, tagline, instructions, max_discount_bps, autonomy_mode, tool_allowlist, policy_version, policy_hash, config_version, status), `ConfigUpsert` (dataclass, all optional fields + `expected_config_version: int | None`), `class OrgScopedStore` with:
  `__init__(engine, *, organization_id: str, agent_id: str | None = None)`
  `get_config(agent_id: str) -> ConfigSnapshot | None`
  `upsert_config(agent_id: str, agent_upsert: ConfigUpsert, *, seller_id: str, name: str, tagline: str = "") -> ConfigSnapshot`
  `list_products() -> list[dict]`
  `import_products(products: list[dict], *, replace: bool) -> dict`  # keys: inserted, updated, replaced
  `first_sku() -> str | None`
  `find_stock(sku: str) -> dict | None`
  `load_policy() -> SellerPolicy`
  `load_mandate() -> SellerMandate`
  `record_task_ownership(task_id: str, context_id: str | None = None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_shared_store.py
import pytest, pytest_asyncio, json
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from seller_agent.shared_store import OrgScopedStore, TenantContextError, ConfigUpsert


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_store_requires_organization(engine):
    with pytest.raises(TenantContextError):
        OrgScopedStore(engine, organization_id="")


async def test_create_and_get_config(engine):
    store = OrgScopedStore(engine, organization_id="orgA", agent_id="agent_acme")
    snap = await store.upsert_config(
        "agent_acme",
        ConfigUpsert(name="Acme", instructions="hello", tool_allowlist=["commerce.catalog.search"]),
        seller_id="acme", name="Acme", tagline="Test",
    )
    assert snap.config_version == 1 and snap.policy_version == 1 and snap.policy_hash
    snap2 = await store.get_config("agent_acme")
    assert snap2.instructions == "hello" and snap2.config_version == 1


async def test_org_isolation(engine):
    a = OrgScopedStore(engine, organization_id="orgA")
    b = OrgScopedStore(engine, organization_id="orgB")
    await a.upsert_config("agent_a", ConfigUpsert(instructions="A"), seller_id="a", name="A", tagline="")
    assert await b.get_config("agent_a") is None


async def test_expected_config_version_mismatch(engine):
    store = OrgScopedStore(engine, organization_id="orgA")
    await store.upsert_config("agent_a", ConfigUpsert(instructions="A"), seller_id="a", name="A", tagline="")
    with pytest.raises(Exception) as exc:
        await store.upsert_config(
            "agent_a", ConfigUpsert(instructions="B", expected_config_version=99),
            seller_id="a", name="A", tagline="",
        )
    assert getattr(exc.value, "current_version", None) == 1


async def test_import_products_upsert_and_replace(engine):
    store = OrgScopedStore(engine, organization_id="orgA")
    p = {"sku": "S1", "name": "Prod", "category": "c",
         "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80, "stock_on_hand": 5}
    r1 = await store.import_products([p], replace=False)
    assert r1 == {"inserted": 1, "updated": 0, "replaced": 0}
    r2 = await store.import_products([{**p, "stock_on_hand": 9}], replace=False)
    assert r2 == {"inserted": 0, "updated": 1, "replaced": 0}
    r3 = await store.import_products([{**p, "sku": "S2"}], replace=True)
    assert r3["replaced"] == 1
    skus = {row["sku"] for row in await store.list_products()}
    assert skus == {"S2"}


async def test_load_policy_matches_yaml_fixture(engine):
    from commerce_core.pricing import load_policy
    store = OrgScopedStore(engine, organization_id="orgA")
    await store.upsert_config(
        "agent_x",
        ConfigUpsert(instructions="i", max_discount_bps=1000,
                     autonomy_mode="policy_bounded"),
        seller_id="northwind-audio", name="Northwind Audio",
        tagline="Premium audio",
    )
    row = {"sku": "MM-T", "name": "T", "category": "Electronics",
           "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
           "floor_unit_price_cents": 80, "stock_on_hand": 3,
           "concession_ladder_cents": [90, 85]}
    await store.import_products([row], replace=False)
    policy = await store.load_policy()
    assert policy.name == "Northwind Audio" and policy.catalog()[0].sku == "MM-T"
```

- [ ] **Step 2: Run it (fails, module missing)**

Run: `uv run pytest tests/unit/test_shared_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `shared_store.py`**

```python
# apps/seller_agent/seller_agent/shared_store.py
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from commerce_core.pricing import SellerPolicy, SellerCatalogProduct
from seller_agent.mandate import SellerMandate


def canonical_json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class TenantContextError(RuntimeError):
    """Raised when a store is used without an organization context."""


class ConfigConflict(Exception):
    def __init__(self, current_version: int) -> None:
        super().__init__(f"expected_config_version mismatch; current is {current_version}")
        self.current_version = current_version


@dataclass
class ConfigUpsert:
    name: str | None = None
    tagline: str | None = None
    instructions: str | None = None
    max_discount_bps: int | None = None
    autonomy_mode: str | None = None
    tool_allowlist: list[str] | None = None
    expected_config_version: int | None = None


@dataclass
class ConfigSnapshot:
    agent_id: str
    organization_id: str
    seller_id: str
    name: str
    tagline: str
    instructions: str
    max_discount_bps: int
    autonomy_mode: str
    tool_allowlist: list[str]
    policy_version: int
    policy_hash: str
    config_version: int
    status: str


_POLICY_WEIGHTS = ("instructions", "tool_allowlist", "max_discount_bps", "autonomy_mode")


def _snapshot(row) -> ConfigSnapshot:
    return ConfigSnapshot(
        agent_id=row.agent_id, organization_id=row.organization_id,
        seller_id=row.seller_id, name=row.name, tagline=row.tagline or "",
        instructions=row.instructions or "",
        max_discount_bps=row.max_discount_bps, autonomy_mode=row.autonomy_mode,
        tool_allowlist=json.loads(row.tool_allowlist_json or "[]"),
        policy_version=row.policy_version, policy_hash=row.policy_hash,
        config_version=row.config_version, status=row.status,
    )


def _policy_hash(payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(payload))


class OrgScopedStore:
    def __init__(self, engine: AsyncEngine, *, organization_id: str,
                 agent_id: str | None = None) -> None:
        org = (organization_id or "").strip()
        if not org:
            raise TenantContextError("organization_id is required")
        self.engine = engine
        self.organization_id = org
        self.agent_id = agent_id

    async def get_config(self, agent_id: str) -> ConfigSnapshot | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT * FROM seller_configs WHERE agent_id = :a AND organization_id = :o"),
                {"a": agent_id, "o": self.organization_id},
            )).first()
        return _snapshot(row) if row else None

    async def upsert_config(self, agent_id: str, up: ConfigUpsert, *,
                            seller_id: str, name: str, tagline: str = "") -> ConfigSnapshot:
        current = await self.get_config(agent_id)
        if (up.expected_config_version is not None and current is not None
                and current.config_version != up.expected_config_version):
            raise ConfigConflict(current.config_version)
        base = current or ConfigSnapshot(
            agent_id=agent_id, organization_id=self.organization_id,
            seller_id=seller_id, name=name, tagline=tagline,
            instructions="", max_discount_bps=1000, autonomy_mode="policy_bounded",
            tool_allowlist=[], policy_version=1, policy_hash="",
            config_version=0, status="draft",
        )
        merged = ConfigSnapshot(
            agent_id=agent_id, organization_id=self.organization_id,
            seller_id=current.seller_id if current else seller_id,
            name=up.name if up.name is not None else base.name,
            tagline=up.tagline if up.tagline is not None else base.tagline,
            instructions=up.instructions if up.instructions is not None else base.instructions,
            max_discount_bps=(up.max_discount_bps if up.max_discount_bps is not None
                              else base.max_discount_bps),
            autonomy_mode=(up.autonomy_mode if up.autonomy_mode is not None
                           else base.autonomy_mode),
            tool_allowlist=(list(up.tool_allowlist) if up.tool_allowlist is not None
                            else base.tool_allowlist),
            policy_version=base.policy_version, policy_hash=base.policy_hash,
            config_version=base.config_version + 1, status=base.status,
        )
        policy_payload = {key: getattr(merged, key) for key in _POLICY_WEIGHTS}
        policy_payload["tool_allowlist"] = sorted(merged.tool_allowlist)
        new_hash = _policy_hash(policy_payload)
        policy_changed = new_hash != (current.policy_hash if current else "")
        merged.policy_version = ((base.policy_version + 1)
                                 if (policy_changed and current) else base.policy_version)
        merged.policy_hash = new_hash
        async with self.engine.begin() as conn:
            if current:
                await conn.execute(text(
                    """UPDATE seller_configs SET name=:name, tagline=:tagline,
                       instructions=:ins, max_discount_bps=:m, autonomy_mode=:mode,
                       tool_allowlist_json=:al, policy_version=:pv, policy_hash=:ph,
                       config_version=:cv, updated_at=:now
                       WHERE agent_id=:a AND organization_id=:o"""
                ), {"name": merged.name, "tagline": merged.tagline, "ins": merged.instructions,
                    "m": merged.max_discount_bps, "mode": merged.autonomy_mode,
                    "al": json.dumps(merged.tool_allowlist),
                    "pv": merged.policy_version, "ph": merged.policy_hash,
                    "cv": merged.config_version, "a": agent_id,
                    "o": self.organization_id, "now": datetime.now(UTC).isoformat()})
            else:
                await conn.execute(text(
                    """INSERT INTO seller_configs
                       (agent_id, organization_id, seller_id, name, tagline,
                        instructions, max_discount_bps, autonomy_mode,
                        tool_allowlist_json, policy_version, policy_hash, config_version)
                       VALUES (:a, :o, :sid, :name, :tag, :ins, :m, :mode, :al, :pv, :ph, :cv)"""
                ), {"a": agent_id, "o": self.organization_id, "sid": seller_id,
                    "name": merged.name, "tag": merged.tagline,
                    "ins": merged.instructions, "m": merged.max_discount_bps,
                    "mode": merged.autonomy_mode,
                    "al": json.dumps(merged.tool_allowlist),
                    "pv": merged.policy_version, "ph": merged.policy_hash,
                    "cv": merged.config_version})
        return merged

    async def list_products(self) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                text("SELECT * FROM products WHERE organization_id = :o"),
                {"o": self.organization_id},
            )).all()
        return [dict(row._mapping) for row in rows]

    async def import_products(self, products: list[dict], *, replace: bool) -> dict:
        counts = {"inserted": 0, "updated": 0, "replaced": 0}
        async with self.engine.begin() as conn:
            if replace:
                skus = [p["sku"] for p in products]
                placeholder = ", ".join(f":s{i}" for i in range(len(skus))) or "'__none__'"
                params = {f"s{i}": s for i, s in enumerate(skus)} | {"o": self.organization_id}
                result = await conn.execute(
                    text(f"DELETE FROM products WHERE organization_id = :o AND sku NOT IN ({placeholder})"),
                    params)
                counts["replaced"] = result.rowcount if hasattr(result, "rowcount") else 0
            for p in products:
                existing = (await conn.execute(
                    text("SELECT sku FROM products WHERE organization_id=:o AND sku=:s"),
                    {"o": self.organization_id, "s": p["sku"]},
                )).first()
                cols = {k: p.get(k) for k in (
                    "sku", "name", "category", "description",
                    "list_unit_price_cents", "original_unit_price_cents",
                    "initial_unit_price_cents", "floor_unit_price_cents",
                    "concession_ladder_json", "warranty_addons_json",
                    "base_warranty_months", "returns_days", "delivery_days",
                    "stock_on_hand", "incoming_stock", "incoming_days",
                    "image_emoji", "color", "rating", "reviews", "tag",
                    "color_name", "sustainability_certified",
                ) if k in p}
                if "concession_ladder_cents" in p:
                    cols["concession_ladder_json"] = json.dumps(p["concession_ladder_cents"])
                if "warranty_addons_cents" in p:
                    cols["warranty_addons_json"] = json.dumps(p["warranty_addons_cents"])
                cols["organization_id"] = self.organization_id
                insert_cols = ", ".join(cols)
                insert_vals = ", ".join(f":{k}" for k in cols)
                update_cols = ", ".join(f"{k}=:{k}" for k in cols if k != "sku")
                await conn.execute(text(
                    f"INSERT INTO products ({insert_cols}) VALUES ({insert_vals}) "
                    f"ON CONFLICT(organization_id, sku) DO UPDATE SET {update_cols}"
                ), cols)
                await conn.execute(text(
                    """INSERT INTO inventory (organization_id, sku, on_hand, incoming, incoming_days)
                       VALUES (:o, :sku, :oh, :inc, :ind)
                       ON CONFLICT(organization_id, sku) DO UPDATE SET
                         on_hand=:oh, incoming=:inc, incoming_days=:ind"""
                ), {"o": self.organization_id, "sku": p["sku"],
                    "oh": p.get("stock_on_hand", 0), "inc": p.get("incoming_stock", 0),
                    "ind": p.get("incoming_days")})
                if existing:
                    counts["updated"] += 1
                else:
                    counts["inserted"] += 1
        return counts

    async def first_sku(self) -> str | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT sku FROM products WHERE organization_id=:o ORDER BY sku LIMIT 1"),
                {"o": self.organization_id})).first()
        return row[0] if row else None

    async def find_stock(self, sku: str) -> dict | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT on_hand, incoming, incoming_days FROM inventory "
                     "WHERE organization_id=:o AND sku=:s"),
                {"o": self.organization_id, "s": sku})).first()
        return dict(row._mapping) if row else None

    async def load_policy(self) -> SellerPolicy:
        products = await self.list_products()
        snapshot = await self.get_config(self.agent_id or "")
        if snapshot is None:
            raise TenantContextError("seller config not found for agent")
        first = products[0] if products else {}
        catalog = [
            SellerCatalogProduct(
                sku=p["sku"], name=p["name"], category=p.get("category") or "general",
                description=p.get("description") or "",
                list_unit_price_cents=p["list_unit_price_cents"],
                original_unit_price_cents=p.get("original_unit_price_cents"),
                floor_unit_price_cents=p["floor_unit_price_cents"],
                initial_unit_price_cents=p["initial_unit_price_cents"],
                concession_ladder_cents=json.loads(p.get("concession_ladder_json") or "[]"),
                base_warranty_months=p.get("base_warranty_months"),
                warranty_addons_cents=json.loads(p.get("warranty_addons_json") or "{}"),
                returns_days=p.get("returns_days"), delivery_days=p.get("delivery_days"),
                stock_on_hand=p.get("stock_on_hand"),
                incoming_stock=p.get("incoming_stock"),
                incoming_days=p.get("incoming_days"),
                image_emoji=p.get("image_emoji") or "📦",
                color=p.get("color") or "#eef2ed", rating=p.get("rating"),
                reviews=p.get("reviews") or "", tag=p.get("tag") or "",
                color_name=p.get("color_name") or "black",
                sustainability_certified=(
                    None if p.get("sustainability_certified") is None
                    else bool(p["sustainability_certified"])),
            )
            for p in products
        ]
        defaults = {
            "list_unit_price_cents": first.get("list_unit_price_cents") or 1,
            "floor_unit_price_cents": first.get("floor_unit_price_cents") or 1,
            "initial_unit_price_cents": first.get("initial_unit_price_cents") or 1,
            "concession_ladder_cents": json.loads(first.get("concession_ladder_json") or "[]"),
            "base_warranty_months": first.get("base_warranty_months") or 12,
            "warranty_addons_cents": json.loads(first.get("warranty_addons_json") or "{}"),
            "returns_days": first.get("returns_days") or 30,
            "delivery_days": first.get("delivery_days") or 5,
            "stock_on_hand": first.get("stock_on_hand") or 0,
            "incoming_stock": first.get("incoming_stock") or 0,
            "incoming_days": first.get("incoming_days"),
            "sustainability_certified": bool(first.get("sustainability_certified") or False),
            "rating": first.get("rating") or 4.5,
        }
        return SellerPolicy(
            seller_id=snapshot.seller_id,
            name=snapshot.name,
            tagline=snapshot.tagline,
            categories=sorted({p.get("category") or "general" for p in products}) or ["general"],
            **defaults,
            products=catalog,
            mandate=None,
        )

    async def load_mandate(self) -> SellerMandate:
        return SellerMandate()

    async def record_task_ownership(self, task_id: str, context_id: str | None = None) -> None:
        if not self.agent_id:
            raise TenantContextError("task ownership requires a bound agent")
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "INSERT OR IGNORE INTO task_ownership (task_id, organization_id, agent_id, context_id) "
                "VALUES (:t, :o, :a, :c)"
            ), {"t": task_id, "o": self.organization_id,
                "a": self.agent_id, "c": context_id})
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_shared_store.py -v`
Expected: PASS. (`pytest_asyncio` is already used in this repo's fixtures; follow `tests/unit/conftest.py` if an event-loop fixture exists.)

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/shared_store.py tests/unit/test_shared_store.py
git commit -m "feat(seller-agent): org-scoped store (fail closed) for shared sellers.db"
```

---

### Task 3: Example catalog assets

**Files:**
- Create: `docs/fixtures/catalog/example-catalog.json` (canonical test fixture) and the **same** content copied to `apps/console/public/example-catalog.{json,yaml}`
- Create: `apps/console/public/example-catalog-template.yaml` (annotated)
- Create: `apps/seller_agent/seller_agent/catalog_import.py`
- Test: `tests/unit/test_catalog_import.py`

**Interfaces:**
- Produces: `MAX_IMPORT_BYTES = 2_097_152`, `MAX_PRODUCTS = 1000`,
  `class CatalogImportError(Exception): .errors: list[dict]  # each {row, field, message}`,
  `class ImportProduct(BaseModel)` (extra=forbid; required `sku, name, category, list_unit_price_cents, initial_unit_price_cents, floor_unit_price_cents`; optional rest),
  `def parse_catalog_document(content: str) -> list[ImportProduct]  # raises CatalogImportError or documents a zero-write pass`

- [ ] **Step 1: Write both example catalogs** (IDs are literal placeholders you fill with real values — content shown is the actual intended shape):

```json
{
  "version": 1,
  "currency": "USD",
  "products": [
    {"sku": "EX-LAPTOP-M4", "name": "ExamplePro 14 Laptop", "category": "Electronics",
     "description": "14-inch laptop, 16GB RAM, 512GB SSD",
     "list_unit_price_cents": 149900, "original_unit_price_cents": 179900,
     "initial_unit_price_cents": 139900, "floor_unit_price_cents": 129900,
     "concession_ladder_cents": [139900, 134900, 131900],
     "base_warranty_months": 12, "warranty_addons_cents": {"12": 0, "24": 1900},
     "returns_days": 30, "delivery_days": 5, "stock_on_hand": 25,
     "incoming_stock": 10, "incoming_days": 7,
     "image_emoji": "💻", "color": "#eaf0fb", "rating": 4.6, "tag": "Popular"}
  ]
}
```

Create 4 products with the same shape (mix Electronics/Home & Living), then `example-catalog.yaml` mirrors it; the template YAML carries a comment header listing every field with defaults (schema = `ImportProduct`).

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_catalog_import.py
import json, pytest, yaml

from seller_agent.catalog_import import parse_catalog_document, CatalogImportError

GOOD = json.dumps({"version": 1, "currency": "USD", "products": [
    {"sku": "S1", "name": "One", "category": "c", "list_unit_price_cents": 100,
     "initial_unit_price_cents": 90, "floor_unit_price_cents": 80, "stock_on_hand": 1},
]})


def test_parses_json():
    products = parse_catalog_document(GOOD)
    assert products[0].sku == "S1"

def test_parses_yaml():
    products = parse_catalog_document(yaml.safe_dump(json.loads(GOOD)))
    assert products[0].sku == "S1"

def test_rejects_floor_above_initial():
    bad = json.dumps({"version": 1, "products": [
        {"sku": "S1", "name": "One", "category": "c", "list_unit_price_cents": 100,
         "initial_unit_price_cents": 70, "floor_unit_price_cents": 80, "stock_on_hand": 1},
    ]})
    with pytest.raises(CatalogImportError) as exc:
        parse_catalog_document(bad)
    assert any(e["field"] == "floor_unit_price_cents" for e in exc.value.errors)

def test_rejects_duplicate_sku():
    dup = json.loads(GOOD)
    dup["products"].append(dup["products"][0])
    with pytest.raises(CatalogImportError) as exc:
        parse_catalog_document(json.dumps(dup))
    assert any("duplicate" in e["message"].lower() for e in exc.value.errors)

def test_rejects_unknown_field():
    bad = json.loads(GOOD)
    bad["products"][0]["wat"] = 1
    with pytest.raises(CatalogImportError) as exc:
        parse_catalog_document(json.dumps(bad))

def test_size_cap():
    with pytest.raises(CatalogImportError):
        parse_catalog_document("x" * (2 * 1024 * 1024 + 1))

def test_product_cap():
    many = {"version": 1, "products": [
        {"sku": f"S{i}", "name": "n", "category": "c", "list_unit_price_cents": 100,
         "initial_unit_price_cents": 90, "floor_unit_price_cents": 80, "stock_on_hand": 0}
        for i in range(1001)
    ]}
    with pytest.raises(CatalogImportError):
        parse_catalog_document(json.dumps(many))

def test_example_assets_are_valid():
    from pathlib import Path
    fixture = Path("scripts/fixtures/example-catalog.json").read_text()
    assert parse_catalog_document(fixture)
    fixture_yaml = Path("scripts/fixtures/example-catalog.yaml").read_text()
    assert parse_catalog_document(fixture_yaml)
```

- [ ] **Step 3: Fail. Implement `catalog_import.py`.**

```python
# apps/seller_agent/seller_agent/catalog_import.py
from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_PRODUCTS = 1000


class ImportErrorEntry(BaseModel):
    row: int | None = None
    field: str | None = None
    message: str


class CatalogImportError(Exception):
    def __init__(self, errors: list[ImportErrorEntry]) -> None:
        super().__init__("catalog import failed")
        self.errors = [e.model_dump() for e in errors]


class ImportProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    description: str = ""
    list_unit_price_cents: int = Field(gt=0)
    original_unit_price_cents: int | None = Field(default=None, gt=0)
    initial_unit_price_cents: int = Field(gt=0)
    floor_unit_price_cents: int = Field(gt=0)
    concession_ladder_cents: list[int] = Field(default_factory=list)
    warranty_addons_cents: dict[int, int] = Field(default_factory=dict)
    base_warranty_months: int = Field(default=12, ge=0)
    returns_days: int = Field(default=30, ge=0)
    delivery_days: int = Field(default=5, gt=0)
    stock_on_hand: int = Field(default=0, ge=0)
    incoming_stock: int = Field(default=0, ge=0)
    incoming_days: int | None = None
    image_emoji: str = "📦"
    color: str = "#eef2ed"
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    reviews: str = ""
    tag: str = ""
    color_name: str = "black"
    sustainability_certified: bool | None = None

    @model_validator(mode="after")
    def _ordering(self):
        if not (self.floor_unit_price_cents <= self.initial_unit_price_cents
                <= self.list_unit_price_cents):
            raise ValueError(
                "floor_unit_price_cents <= initial_unit_price_cents <= list_unit_price_cents"
            )
        for v in self.concession_ladder_cents:
            if not (self.floor_unit_price_cents <= v <= self.list_unit_price_cents):
                raise ValueError("concession_ladder_cents values out of bounds")
        return self


def _sniff(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise CatalogImportError(
                [ImportErrorEntry(message=f"document is neither JSON nor YAML: {e}")]
            )


def parse_catalog_document(content: str) -> list[ImportProduct]:
    if len(content.encode()) > MAX_IMPORT_BYTES:
        raise CatalogImportError([ImportErrorEntry(message="document exceeds 2 MB")])
    doc = _sniff(content)
    if not isinstance(doc, dict):
        raise CatalogImportError(
            [ImportErrorEntry(message="top-level document must be an object")]
        )
    raw_products = doc.get("products")
    if not isinstance(raw_products, list):
        raise CatalogImportError(
            [ImportErrorEntry(field="products", message="products must be a list")]
        )
    if len(raw_products) > MAX_PRODUCTS:
        raise CatalogImportError(
            [ImportErrorEntry(field="products", message=f"more than {MAX_PRODUCTS} products")]
        )
    errors: list[ImportErrorEntry] = []
    products: list[ImportProduct] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_products):
        if not isinstance(raw, dict):
            errors.append(ImportErrorEntry(row=index + 1, message="product must be an object"))
            continue
        try:
            product = ImportProduct.model_validate(raw)
            if product.sku in seen:
                errors.append(ImportErrorEntry(
                    row=index + 1, field="sku", message=f"duplicate sku {product.sku}"))
            seen.add(product.sku)
            products.append(product)
        except Exception as e:  # pydantic validation error text is long; extract fields
            msg = str(e).replace("\n", " ")[:400]
            errors.append(ImportErrorEntry(row=index + 1, message=msg))
    if errors:
        raise CatalogImportError(errors)
    return products
```

- [ ] **Step 4: Tests pass**

Run: `uv run pytest tests/unit/test_catalog_import.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/catalog_import.py tests/unit/test_catalog_import.py scripts/fixtures apps/console/public/example-catalog.json apps/console/public/example-catalog.yaml apps/console/public/example-catalog-template.yaml
git commit -m "feat(seller-agent): catalog import document parser + example fixtures"
```

---

### Task 4: Shared mode + internal service endpoints

**Files:**
- Modify: `apps/seller_agent/seller_agent/settings.py`, `apps/seller_agent/seller_agent/server.py`
- Create: `apps/seller_agent/seller_agent/internal_routes.py`
- Test: `tests/unit/test_internal_routes.py`

**Interfaces:**
- Consumes: Task 2 `OrgScopedStore`, `ConfigUpsert`; Task 3 parser (Task 2 also exports the hashing helpers)
- Produces: `internal_router` (APIRouter, prefix `/internal`) with:
  `POST /internal/agent-configs` → body `{agent_id, organization_id, seller_id, name?, tagline?, instructions?, max_discount_bps?, autonomy_mode?, tool_allowlist?, expected_config_version?}` → `{agent_id, config_version, policy_version, policy_hash, status}` — 401 without valid `X-Internal-Token`, 403 on header/payload org mismatch, 409 on config-version conflict
  `POST /internal/catalog/import` → body `{document: str, replace_catalog?: bool}` + headers `X-Org-Id`, `X-Agent-Id` → `{inserted, updated, replaced, errors: []}` — 422 on validation failure (no writes)
  `GET /internal/agent-configs/{agent_id}` (headers `X-Org-Id`) → sanitized snapshot JSON
  `POST /internal/test-suite` → `{agent_id, credential: str, revoked_credential: str}` → `{passed: bool, checks: [{name, passed, detail}]}`
  Error body shape: `{"errors": [ {row, field, message} | {code, message} ]}`.

- [ ] **Step 1: settings additions**

```python
    # apps/seller_agent/seller_agent/settings.py — append to class Settings:
    config_source: Literal["file", "shared"] = Field(default="file", validation_alias=AliasChoices("SELLER_CONFIG_SOURCE"))
    shared_db_url: str = Field(default="sqlite+aiosqlite:///./data/sellers.db", validation_alias=AliasChoices("SELLER_SHARED_DB_URL"))
    internal_api_token: str | None = Field(default=None, validation_alias=AliasChoices("SELLER_INTERNAL_TOKEN"))
    test_identity_token: str | None = Field(default=None, validation_alias=AliasChoices("SELLER_TEST_IDENTITY_TOKEN"))
```

- [ ] **Step 2: write failing tests**

```python
# tests/unit/test_internal_routes.py
import json, pytest, pytest_asyncio
from httpx import ASGITransport, AsyncClient

from seller_agent.settings import Settings
from seller_agent.server import create_app

INTERNAL = "internal-test-token"
ORG = "org_A"
AGENT = "agent_demo"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    settings = Settings(
        config_source="shared",
        shared_db_url=f"sqlite+aiosqlite:///{tmp_path}/sellers.db",
        internal_api_token=INTERNAL,
        verifund_mode="off",
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def h(org=ORG, agent=AGENT, token=INTERNAL):
    return {"x-internal-token": token, "x-org-id": org, "x-agent-id": agent}


async def test_internal_routes_require_token(client):
    r = await client.post("/internal/agent-configs", json={
        "agent_id": AGENT, "organization_id": ORG, "seller_id": "demo", "name": "Demo"})
    assert r.status_code == 401


async def test_agent_configs_create_and_upsert(client):
    body = {"agent_id": AGENT, "organization_id": ORG, "seller_id": "demo",
            "name": "Demo", "instructions": "be nice",
            "tool_allowlist": ["commerce.catalog.search"],
            "max_discount_bps": 1000, "autonomy_mode": "policy_bounded"}
    r1 = await client.post("/internal/agent-configs", json=body, headers=h())
    assert r1.status_code == 200 and r1.json()["config_version"] == 1
    r2 = await client.post("/internal/agent-configs",
                           json={**body, "expected_config_version": 99}, headers=h())
    assert r2.status_code == 409


async def test_catalog_import_validates_and_writes(client):
    doc = json.dumps({"version": 1, "products": [
        {"sku": "T1", "name": "Thing", "category": "c",
         "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80, "stock_on_hand": 2}]})
    r = await client.post("/internal/catalog/import",
                          json={"document": doc}, headers=h())
    assert r.status_code == 200 and r.json()["inserted"] == 1
    bad = json.dumps({"version": 1, "products": [
        {"sku": "T1", "name": "Thing", "category": "c",
         "list_unit_price_cents": 100, "initial_unit_price_cents": 70,
         "floor_unit_price_cents": 80, "stock_on_hand": 2}]})
    r = await client.post("/internal/catalog/import",
                          json={"document": bad}, headers=h())
    assert r.status_code == 422 and len(r.json()["errors"]) >= 1
```

- [ ] **Step 3: implement `internal_routes.py`** (Sketch — executor implements exactly these shapes)

```python
# apps/seller_agent/seller_agent/internal_routes.py
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from seller_agent.catalog_import import parse_catalog_document, CatalogImportError
from seller_agent.shared_store import (
    OrgScopedStore, ConfigUpsert, ConfigConflict, TenantContextError,
)

router = APIRouter(prefix="/internal")


def _require_internal_token(request: Request) -> None:
    settings = request.app.state.settings
    token = request.headers.get("x-internal-token", "")
    if not settings.internal_api_token or not hmac.compare_digest(
            token, settings.internal_api_token):
        raise HTTPException(status_code=401, detail={"code": "internal_auth", "message": "bad internal credential"})


def _org(request: Request) -> str:
    org = (request.headers.get("x-org-id") or "").strip()
    if not org:
        raise HTTPException(status_code=400, detail={"code": "org_required", "message": "x-org-id required"})
    return org


def _agent(request: Request) -> str | None:
    return request.headers.get("x-agent-id")


class AgentConfigBody(BaseModel):
    agent_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    name: str | None = None
    tagline: str | None = None
    instructions: str | None = None
    max_discount_bps: int | None = Field(default=None, ge=0, le=10_000)
    autonomy_mode: str | None = Field(default=None, pattern="^(read_only|assisted|policy_bounded)$")
    tool_allowlist: list[str] | None = None
    expected_config_version: int | None = None


class CatalogImportBody(BaseModel):
    document: str = Field(min_length=2, max_length=2 * 1024 * 1024)
    replace_catalog: bool = False


class TestSuiteBody(BaseModel):
    agent_id: str = Field(min_length=1)
    credential: str = Field(min_length=1)
    revoked_credential: str = Field(min_length=1)


def get_store(request: Request, org: str, agent: str | None = None) -> OrgScopedStore:
    return OrgScopedStore(request.app.state.shared_engine,
                          organization_id=org, agent_id=agent)


@router.post("/agent-configs")
async def upsert_agent_config(body: AgentConfigBody, request: Request,
                              _=Depends(_require_internal_token)):
    org = _org(request)
    if org != body.organization_id:
        raise HTTPException(status_code=403, detail={"code": "org_mismatch", "message": "x-org-id does not match payload"})
    store = get_store(request, org, body.agent_id)
    try:
        snap = await store.upsert_config(
            body.agent_id,
            ConfigUpsert(
                name=body.name, tagline=body.tagline, instructions=body.instructions,
                max_discount_bps=body.max_discount_bps, autonomy_mode=body.autonomy_mode,
                tool_allowlist=body.tool_allowlist,
                expected_config_version=body.expected_config_version),
            seller_id=body.seller_id, name=body.name or body.seller_id,
            tagline=body.tagline or "")
    except ConfigConflict as conflict:
        raise HTTPException(status_code=409,
                            detail={"code": "config_conflict", "config_version": conflict.current_version})
    return snap.__dict__


@router.post("/catalog/import")
async def import_catalog(body: CatalogImportBody, request: Request,
                         _=Depends(_require_internal_token)):
    org = _org(request)
    agent = _agent(request)
    try:
        products = parse_catalog_document(body.document)
    except CatalogImportError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    store = get_store(request, org, agent)
    counts = await store.import_products(
        [p.model_dump() for p in products], replace=body.replace_catalog)
    return {"inserted": counts["inserted"], "updated": counts["updated"],
            "replaced": counts["replaced"], "errors": []}


@router.get("/agent-configs/{agent_id}")
async def get_agent_config(agent_id: str, request: Request,
                           _=Depends(_require_internal_token)):
    org = _org(request)
    store = get_store(request, org, agent_id)
    snap = await store.get_config(agent_id)
    if snap is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_agent", "message": "unknown agent"})
    return snap.__dict__


# /internal/test-suite — implement per the six checks listed above; keep the function name stable.
@router.post("/test-suite")
async def test_suite(body: TestSuiteBody, request: Request,
                     _=Depends(_require_internal_token)):
    ...
```

The `test-suite` body implements the six checks for real (no fakes):

1. **auth** — POST `{verifund_url}/v1/agent-credentials/verify` with `body.credential`; expect 200 with `{"status": "active"}`.
2. **catalog** — `store.first_sku()` is not None.
3. **pricing** — load `policy = await store.load_policy()`; pick first product; assert floor > 0 and `floor <= initial <= list` (re-verify imported invariants end-to-end) and that a buyer offer priced 1¢ below floor is rejected by `commerce_core` policy bound (the same floor check the executor enforces — call the policy's floor checker — see `commerce_core/pricing.py` `floor_price_cents` helpers; if no exported helper exists, assert via `load_policy()` + arithmetic).
4. **a2a** — build a scripted seller graph in-process: `from seller_agent.graph import build_seller_graph`; drive one quote turn with `llm_mode="scripted"` planner against the first product; assert the final artifact parses to an `offer` schema via `commerce_core.a2a_parts` helpers (`part_value`); no network calls.
5. **authority** — take the first product; compute the agent's max concession via `max_discount_bps` and the product floor; assert a deep-discount offer would require approval (assert `initial * (10_000 - max_discount_bps) // 10_000 >= floor` is False for a contrived 50%-off offer) and that `autonomy_mode == "policy_bounded"` escalates.
6. **revocation** — POST verify with `body.revoked_credential`; expect non-200 (or 200 with `status != "active"`).

`passed` is the AND of all six. Each check's `detail` contains a short human-readable string; failures never leak secrets (logged values truncated).

- [ ] **Step 4: server.py wiring (minimal diff)**

In `create_app`, after settings resolution:

```python
    if settings.config_source == "shared":
        shared_engine = create_async_engine(settings.shared_db_url)
        await configure_shared_engine(shared_engine)   # move to lifespan startup
        await create_shared_schema(shared_engine)      # move to lifespan startup
        app.state.shared_engine = shared_engine
        app.include_router(internal_router)
    else:
        app.state.shared_engine = None
```
(Do the shared-engine creation inside the existing `lifespan` block, not at import time; `create_app` is sync.) Set `app.state.settings = settings` so internal routes can read it.

- [ ] **Step 5: tests green**

Run: `uv run pytest tests/unit/test_internal_routes.py -v`
Expected: PASS — with real behaviors above (no fakes); `VERIFUND_MODE=off` must still run `test-suite` without network.

- [ ] **Step 6: Commit**

```bash
git add apps/seller_agent/seller_agent/settings.py apps/seller_agent/seller_agent/server.py apps/seller_agent/seller_agent/internal_routes.py tests/unit/test_internal_routes.py
git commit -m "feat(seller-agent): shared config mode + internal service endpoints"
```

---

### Task 5: Control-plane endpoints (orchestrator)

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` (extend — same file), `.../tenancy/repository.py` (add `latest_test_run`), `.../settings.py` (add `seller_agent_url`, `seller_internal_token`, `registry_url`), `.../agents/lifecycle.py` (registry projection on activate)
- Test: `tests/unit/test_agent_config_routes.py`

**Interfaces:**
- Produces (all under existing `agent_routes.router`, authenticated by `require_identity` + `org:agents:manage`):
  `POST /v1/agents` {display_name?} → 201 `{agent_id, config_version, policy_version, policy_hash, status:"draft"}`; honors `Idempotency-Key`
  `PATCH /v1/agents/{agent_id}/config` {expected_config_version?, name?, instructions?, tool_allowlist?} → 200 snapshot; 409 on conflict
  `PATCH /v1/agents/{agent_id}/policies` {expected_config_version?, max_discount_bps?, autonomy_mode?} → 200 snapshot (same machinery)
  `POST /v1/seller/catalog/import` {document, replace_catalog?: bool} → 200 `{inserted, updated, replaced, errors: []}`; 413 >2MB; 422 invalid doc (relayed errors)
  `POST /v1/agents/{agent_id}/test` (**replacing the hardcoded-True placeholder**) → issues one-time test credential, invokes runtime `/internal/test-suite`, records `agent_test_runs` row, transitions `configuring → testing`, returns `{passed, checks, run_id}`
  `POST /v1/agents/{agent_id}/activate` → gates (verified, no drift, passing run for current hashes, active credential — reuse `activate_agent`) + registry publish of card; returns updated agent row
  `GET /v1/agents/{agent_id}/status` → `{agent_id, status, config_version, policy_version, policy_hash, card_hash, latest_test_run: {...} | null, registry_published: bool}`
  `GET /v1/agents/{agent_id}/card` → pre-publish card preview `{card_json, card_hash, card_url}`

- [ ] **Step 1: settings**

```python
# apps/verifund_control_plane/verifund_control_plane/settings.py — append:
    seller_agent_url: str = "http://127.0.0.1:9201"     # env SELLER_AGENT_URL
    seller_internal_token: str | None = None           # env SELLER_INTERNAL_TOKEN
    registry_url: str = "http://127.0.0.1:9100"        # env REGISTRY_URL
```

Add `verification_client` indirection like existing code does for directory clients, or reuse plain `httpx.AsyncClient` built per call — follow `registry_sync.py` for the target pattern.

- [ ] **Step 2: repository helper (`tenancy/repository.py`, next to `latest_passing_test`)**

```python
    async def latest_test_run(self, agent_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT * FROM agent_test_runs WHERE agent_id = :a ORDER BY started_at DESC, id DESC LIMIT 1"
            ), {"a": agent_id})).first()
        return self._test_run_dict(row) if row else None
```
(Match the existing `_test_run_dict` helper; if absent, mirror `create_test_run`'s shape.)

- [ ] **Step 3: routes (new bodies inside `agents/routes.py`)**

```python
# Settings/deps at top of file pick up request.app.state.settings.

class CreateAgentBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)


class ConfigBody(BaseModel):
    expected_config_version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=128)
    tagline: str | None = Field(default=None, max_length=256)
    instructions: str | None = Field(default=None, max_length=4096)
    tool_allowlist: list[str] | None = None
    max_discount_bps: int | None = Field(default=None, ge=0, le=10_000)
    autonomy_mode: str | None = Field(default=None, pattern="^(read_only|assisted|policy_bounded)$")


class ImportBody(BaseModel):
    document: str = Field(min_length=2, max_length=2 * 1024 * 1024)
    replace_catalog: bool = False
```

For the call to the runtime, factor a tiny module-level helper:

```python
async def _call_runtime(request: Request, path: str, *, headers: dict[str, str], json_body: dict | None = None):
    settings = request.app.state.settings
    if not settings.seller_internal_token:
        raise VerifundError("seller_runtime_unavailable", "seller runtime not configured", status_code=503)
    headers = {**headers, "x-internal-token": settings.seller_internal_token}
    timeout = httpx.Timeout(15.0)
    try:
        async with httpx.AsyncClient(base_url=settings.seller_agent_url, timeout=timeout) as client:
            return await client.post(path, headers=headers, json=json_body or {})
    except httpx.HTTPError as e:
        raise VerifundError("seller_runtime_unavailable", f"seller runtime unreachable: {e}", status_code=503)
```

Endpoint bodies:

```python
@router.post("/v1/agents", status_code=201)
async def create_agent_route(request: Request, response: Response,
                             body: CreateAgentBody = CreateAgentBody()):
    identity = await require_seller_agent_admin(request)   # org:agents:manage on a business org
    idem = request.headers.get("idempotency-key", "")
    display = (body.display_name or "Seller agent").strip()
    store = request.app.state.tenancy
    if idem:
        existing = await replay_idempotency(store, identity.tenant_id, idem)
        if existing:
            response.status_code = 200
            return existing
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    # agents.id is the table PK and globally unique; anchor the public agent
    # id to the globally unique seller_id (registry: seller_id 1:1 organization).
    seller_id = (profile or {}).get("seller_id") or identity.tenant_id[:64]
    agent_id = f"agent_{seller_id}"
    existing = [a for a in await store.list_agents(identity.tenant_id) if a["id"] == agent_id]
    if existing:
        response.status_code = 200
        return {"agent_id": agent_id, "status": existing[0]["status"],
                "config_version": None}
    agent = await store.create_agent(
        organization_id=identity.tenant_id, name=display, created_by=identity.user_id,
        policy_ref=f"{seller_id}/v1", policy_version="1", policy_hash="0" * 64)
    agent_id = agent["id"]
    # runtime creates the seller_configs row (idempotent)
    r = await _call_runtime(request, "/internal/agent-configs",
                            headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
                            json_body={"agent_id": agent_id,
                                       "organization_id": identity.tenant_id,
                                       "seller_id": seller_id,
                                       "name": display, "tagline": (profile or {}).get("tagline") or ""})
    if r.status_code >= 400:
        raise VerifundError("provisioning_failed", r.text, status_code=502)
    await remember_idempotency(request.app.state.tenancy, identity.tenant_id, idem, agent_id, agent)
    return {"agent_id": agent_id, "status": "draft",
            **r.json()}


@router.patch("/v1/agents/{agent_id}/config")
async def update_agent_config(agent_id: str, body: ConfigBody, request: Request):
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)   # 404/403 rules
    r = await _call_runtime(request, "/internal/agent-configs",
                            headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
                            json_body={"agent_id": agent_id,
                                       "organization_id": identity.tenant_id,
                                       "seller_id": (agent.get("policy_ref") or f"{agent_id}/v1").split("/")[0],  # stable seller_id (from policy_ref)
                                       "name": body.name, "tagline": body.tagline,
                                       "instructions": body.instructions,
                                       "tool_allowlist": body.tool_allowlist,
                                       "max_discount_bps": body.max_discount_bps,
                                       "autonomy_mode": body.autonomy_mode,
                                       "expected_config_version": body.expected_config_version})
    if r.status_code == 409:
        raise VerifundError("config_conflict", r.json(), status_code=409)
    if r.status_code >= 400:
        raise VerifundError("runtime_error", r.text, status_code=502)
    return r.json()
```

Notes for the implementer:
- `require_seller_agent_admin(request)`: resolve identity via `require_identity`, require organization kind `business`, require `org:agents:manage` in `identity.permissions` → else 403.
- `require_own_agent(request, agent_id, identity)`: load agent; if missing or `agent["organization_id"] != identity.tenant_id` → 404.
- `replay_idempotency` / `remember_idempotency`: implement as tiny audit-event-backed helpers inside `routes.py` (query `audit_events` for `scope='agents'`, `action='agent.created'`, `idempotency_key=<key>`); on replay return stored response body.
- PATCH `/v1/agents/{id}/policies` is the same machinery minus instruction-only fields — factor `_forward_config(request, agent_id, identity, body)` used by both.

`POST /v1/seller/catalog/import`:

```python
@router.post("/v1/seller/catalog/import")
async def catalog_import_route(body: ImportBody, request: Request):
    identity = await require_seller_agent_admin(request)
    r = await _call_runtime(request, "/internal/catalog/import",
                            headers={"x-org-id": identity.tenant_id},
                            json_body={"document": body.document,
                                       "replace_catalog": body.replace_catalog})
    if r.status_code == 422:
        raise VerifundError("catalog_invalid", json.dumps(r.json()), status_code=422)
    if r.status_code >= 400:
        raise VerifundError("runtime_error", r.text, status_code=502)
    return r.json()
```

`POST /v1/agents/{id}/test` (replacing the placeholder — **keep the route path**):

```python
@router.post("/v1/agents/{agent_id}/test")
async def test_agent(agent_id: str, request: Request):
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    credential = await issue_credential(store, identity.tenant_id, agent_id, ["a2a:test"])
    revoked = await issue_credential(store, identity.tenant_id, agent_id, ["a2a:test"])
    await revoke_credential_by_raw(store, identity.tenant_id, revoked)   # burn it for the revocation check
    if agent["status"] in ("draft", "configuring"):
        await store.set_agent_status(agent_id, "testing")
    r = await _call_runtime(request, "/internal/test-suite",
                            headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
                            json_body={"agent_id": agent_id,
                                       "credential": credential,
                                       "revoked_credential": revoked})
    if r.status_code >= 400:
        raise VerifundError("runtime_error", r.text, status_code=502)
    result = r.json()
    run = await store.create_test_run(
        agent_id, identity.tenant_id,
        policy_hash=agent.get("policy_hash") or "",
        card_hash=agent.get("card_hash") or "",
        checks=result["checks"], passed=bool(result["passed"]))
    if not result["passed"]:
        await store.set_agent_status(agent_id, "configuring")   # remediation loop per state machine
    return {"passed": bool(result["passed"]), "checks": result["checks"],
            "run_id": run["id"]}
```

`POST /v1/agents/{id}/activate`:

```python
@router.post("/v1/agents/{agent_id}/activate")
async def activate_agent_route(agent_id: str, request: Request):
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    try:
        activated = await activate_agent(store, agent_id)
    except VerifundError:
        raise
    # registry projection
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    card = build_seller_card(profile, agent)   # local helper; public fields only
    settings = request.app.state.settings
    async with httpx.AsyncClient(base_url=settings.registry_url, timeout=httpx.Timeout(10.0)) as client:
        await publish_agent(client, {**activated, "organization_id": identity.tenant_id},
                            {"card_url": f"{settings.registry_url_base or 'https://agents.verifund.com'}/{seller_id}/.well-known/agent-card.json",
                             "skills": [s["id"] for s in card["skills"]],
                             "card_json": card})
    return {"agent_id": agent_id, "status": activated["status"]}
```

`build_seller_card` (module-level in `registry_sync.py` or a new `agents/cards.py`):

```python
_SKILL_META = {
    "commerce.catalog.search": {"name": "Product Discovery", "description": "Search the seller's product catalog."},
    "commerce.inventory.check": {"name": "Inventory Check", "description": "Check product availability in real time."},
    "commerce.quote": {"name": "Quotation Generation", "description": "Return seller-approved quotations."},
    "commerce.negotiate": {"name": "Pricing Negotiation", "description": "Negotiate offers within approved policies."},
    "commerce.order": {"name": "Order Management", "description": "Create idempotent orders for approved purchases."},
    "commerce.agreement.review": {"name": "Agreement Preparation", "description": "Prepare and review commercial agreements."},
}

def build_seller_card(profile: dict, agent: dict) -> dict:
    allowlist = list(agent.get("tool_allowlist") or [])
    skills = [{"id": skill_id, **_SKILL_META[skill_id], "tags": ["commerce"]}
              for skill_id in allowlist if skill_id in _SKILL_META]
    seller_id = (profile or {}).get("seller_id") or agent.get("id")
    return {
        "name": agent.get("name") or profile_name(profile),
        "description": (profile or {}).get("tagline") or "Verifund seller agent",
        "version": "1.0.0",
        "skills": skills,
        "supportedInterfaces": [{
            "url": f"/{seller_id}/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
            "tenant": agent.get("id"),
        }],
        "capabilities": {"streaming": True},
    }
```

Also `GET /v1/agents/{agent_id}/status` and `GET /v1/agents/{agent_id}/card` (status combines store row + `latest_test_run` + card preview). Register nothing new — `agent_routes.router` is already included in `app.py`.

`revoke_credential_by_raw` — add to `agents/credentials.py`: hash raw token, set `status='revoked'` where stored, return bool.

`activate_agent` (lifecycle) currently verifies verified+drift+test+credential — reuse as-is.

- [ ] **Step 4: tests — `tests/unit/test_agent_config_routes.py`**

Follow `tests/unit/test_agent_credentials.py`'s engine/tenancy fixtures; build the FastAPI app once per test via a module-level fixture that:
- sets `app = create_app()`;
- swaps `app.state.tenancy` with a fresh `TenancyRepository(create_async_engine(tmp_path_db))`;
- swaps `app.state.settings` with test settings;
- injects `app.state.clerk_authenticator = lambda request: {"sub": "user_1", "org_id": "org_1"}` or whatever the existing tenancy tests use — mirror `test_tenancy_identity.py`'s auth-stub pattern exactly.

Mock the runtime and registry at the **httpx transport** boundary. Route the CP's runtime calls through a `runtime_mock` transport: implement in the fixture a small in-process ASGI app emulating `/internal/agent-configs`, `/internal/catalog/import`, `/internal/test-suite` with the *real* semantics of Task 4 (import it from `seller_agent.internal_routes` and wrap) — or simpler for these tests: patch `agents.routes._call_runtime` with `respx`-style shortcut via `httpx.MockTransport` injected into `_call_runtime`. Concretely: rewrite `_call_runtime` to accept the request's `app` state client factory; the test overrides `app.state.runtime_client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))`. Handler:

```python

def runtime_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    org = request.headers.get("x-org-id")
    if "agent-configs" in path:
        payload = json.loads(request.content)
        return httpx.Response(200, json={"agent_id": payload["agent_id"], "config_version": 1,
                                         "policy_version": 1, "policy_hash": "a" * 64,
                                         "status": "draft"})
    if "catalog/import" in path:
        return httpx.Response(200, json={"inserted": 1, "updated": 0, "replaced": 0, "errors": []})
    if "test-suite" in path:
        return httpx.Response(200, json={"passed": True, "checks": [{"name": n, "passed": True, "detail": "ok"} for n in
            ["auth", "catalog", "pricing", "a2a", "authority", "revocation"]]})
    return httpx.Response(404, json={"errors": []})
```

Assert: create is idempotent (same `Idempotency-Key` → same `agent_id`, 200 second time); `org:agents:manage` missing → 403; foreign agent → 404; PATCH conflict surfaces as 409; test route returns six checks all true with passing `run_id`, and failure path sets status back to `configuring`; activate endpoint rejects when seller unverified (403) and when no passing test run (409).

- [ ] **Step 5: full backend test run**

Run: `uv run pytest tests/unit/test_agent_config_routes.py tests/integration/test_onboarding_agent_flow.py -v`
Expected: PASS (the integration test is Task 6 — write it after Task 5's unit tests pass; run only the unit file here)

- [ ] **Step 6: commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents/routes.py apps/verifund_control_plane/verifund_control_plane/agents/credentials.py apps/verifund_control_plane/verifund_control_plane/agents/lifecycle.py apps/verifund_control_plane/verifund_control_plane/agents/cards.py apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py apps/verifund_control_plane/verifund_control_plane/settings.py tests/unit/test_agent_config_routes.py
git commit -m "feat(control-plane): agent config/catalog/import/activation endpoints + registry publish"
```

---

### Task 6: CP ↔ runtime contract tests (real HTTP transport)

**Files:**
- Test: `tests/integration/test_onboarding_agent_flow.py`

**Difference from Task 5:** instead of mocking `_call_runtime`, run the *actual* shared seller app in-process (`SellerAgentSettings(config_source="shared", shared_db_url=tmp file)` → `create_app(...)` mounted on the same test event loop) and point the control plane's `seller_agent_url` at a real localhost port bound via `httpx` ASGI transport — simplest: keep using MockTransport wrapping the seller app: `transport = httpx.ASGITransport(app=seller_app)` passed through `app.state.runtime_client_factory`. No network.

- [ ] **Step 1:** write the failing test describing the whole saga:

```python
import json
from pathlib import Path

EXAMPLE = Path("scripts/fixtures/example-catalog.json").read_text()


async def test_full_agent_configuration_flow(tmp_path):
    seller = make_shared_seller(tmp_path)     # tmp file, internal token set
    cp = make_cp(tmp_path, runtime_transport=seller)  # registry via MockTransport too
    org = await create_verified_business_org(cp, clerk_org_id="org_1", user_id="user_1")

    r = post(cp, "/v1/agents", json={"display_name": "Acme Industrial"}, headers=auth(org))
    agent_id = r.json()["agent_id"]
    assert agent_id.startswith("agent_")

    r = patch(cp, f"/v1/agents/{agent_id}/config",
              json={"instructions": "Be crisp.", "max_discount_bps": 1500}, headers=auth(org))
    assert r.json()["policy_version"] >= 1

    r = patch(cp, f"/v1/agents/{agent_id}/policies",
              json={"autonomy_mode": "policy_bounded"}, headers=auth(org))
    assert r.json()["autonomy_mode"] == "policy_bounded"

    r = post(cp, "/v1/seller/catalog/import",
             json={"document": EXAMPLE}, headers=auth(org))
    assert r.json()["inserted"] >= 1

    r = post(cp, f"/v1/agents/{agent_id}/test", json={}, headers=auth(org))
    assert r.json()["passed"] is True
    assert [c["name"] for c in r.json()["checks"]] == [
        "auth", "catalog", "pricing", "a2a", "authority", "revocation"]

    r = post(cp, f"/v1/agents/{agent_id}/activate", json={}, headers=auth(org))
    assert r.json()["status"] == "active"

    r = get(cp, f"/v1/agents/{agent_id}/status", headers=auth(org))
    assert r.json()["status"] == "active"
```

- [ ] **Step 2:** iterate until PASS; assert cross-tenant invisibility explicitly:

```python
    org_b = await create_verified_business_org(cp, clerk_org_id="org_2", user_id="user_2")
    r = get(cp, f"/v1/agents/{agent_id}/status", headers=auth(org_b))
    assert r.status_code == 404
```

- [ ] **Step 3:** commit `tests/integration/test_onboarding_agent_flow.py`

```bash
git commit -m "test: full onboarding agent saga with real in-process runtime"
```

---

### Task 7: Console — wizard steps, components, portal page

**Files:**
- Create: `apps/console/lib/agent-api.ts`, `apps/console/lib/agent-types.ts`
- Create: `apps/console/components/seller-agent/{AgentIdentityPanel,InstructionEditor,CapabilityGrid,PolicyPanel,AgentCardPreview,CatalogImportPanel,TestResultsPanel,ActivationPanel}.tsx`
- Create pages: `apps/console/app/(seller-onboarding)/seller/onboarding/{integrations,agent_setup,policies,testing,activation}/page.tsx`
- Create: `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts`
- Create: `apps/console/app/seller/agent/page.tsx`; modify `components/seller/seller-nav.tsx` (add Agent entry)
- Test: `apps/console/tests/lib/agent-api.test.ts`, `apps/console/tests/lib/example-catalog.test.ts`

**Interfaces (agent-api.ts):**

```ts
export type AgentSnapshot = {
  agent_id: string; status: "draft" | "configuring" | "testing" | "active";
  config_version: number; policy_version: number; policy_hash: string;
  tool_allowlist?: string[]; instructions?: string;
};
export async function getAgent(agentId: string): Promise<AgentSnapshot | null>         // GET /v1/agents/{id}/status
export async function createAgent(displayName?: string): Promise<AgentSnapshot>          // POST /v1/agents
export async function saveConfig(agentId: string, patch: Partial<{...}>): Promise<AgentSnapshot> // PATCH .../config
export async function savePolicies(agentId: string, patch: { autonomy_mode?: string; max_discount_bps?: number; expected_config_version?: number }): Promise<AgentSnapshot>
export async function importCatalog(document: string, replace?: boolean): Promise<{ inserted: number; updated: number; replaced: number; errors: Array<{ row: number | null; field: string | null; message: string }> }>
export async function runAgentTests(agentId: string): Promise<{ passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }>; run_id: string }>
export async function activateAgent(agentId: string): Promise<{ status: string }>
export async function getAgentCard(agentId: string): Promise<{ card_json: Record<string, unknown>; card_hash: string; card_url: string }>
```
All server-side (import `auth` from `@clerk/nextjs/server`, same `controlPlaneForUser` pattern as `control-plane.ts`), `no-store`, 15s timeout, throw `SellerApiError` on !ok.

- [ ] **Step 1: types + API client (TDD with vitest)**

```ts
// apps/console/tests/lib/agent-api.test.ts — sketch the asserted contract:
import { controlPlaneForUser } from "@/lib/control-plane";   // wrap, don't duplicate
// vitest: mock global fetch; assert URLs, bearer header present, body shapes, error mapping.
// example: saveConfig posts to `${CONTROL_PLANE}/v1/agents/agent_x/config` with method PATCH.
```

- [ ] **Step 2: components (each is a client component + its form does fetch against actions via `useActionState` or plain async `await`)** — follow `components/ui/panel.tsx`, `components/ui/button.tsx` and existing `seller/` component idioms.

Each component has **three states**: loading, saved (last-saved config_version), error (field-level message from CP). `CapabilityGrid` maps these keys:

```ts
const CAPABILITIES = [
  { id: "commerce.catalog.search", label: "Product discovery", description: "Search the seller's catalog" },
  { id: "commerce.inventory.check", label: "Inventory checking", description: "Check availability" },
  { id: "commerce.quote", label: "Quotation generation", description: "Seller-approved quotations" },
  { id: "commerce.negotiate", label: "Price negotiation", description: "Respond to offers and counteroffers" },
  { id: "commerce.agreement.review", label: "Agreement preparation", description: "Prepare proposed agreements" },
  { id: "commerce.order", label: "Order management", description: "Create idempotent orders — recommended off until policies are settled" },
] as const;
```
All default `true` (O14 divergence — do not "fix").

`CatalogImportPanel` responsibilities: file input (accept=".json,.yaml,.yml,application/json,application/octet-stream,text/yaml"), paste area with live character counter, "Load example catalog" button (fetches `/example-catalog.json` → imports), download links for template (`/example-catalog-template.yaml`) and example, explicit error table (`row`, `field`, `message`), upsert/replace toggle that enables `replace_catalog: true` **behind a second confirm** (`window.confirm("This deletes products not in the file. Continue?")`).

`TestResultsPanel`: "Run checks" button → calls action → spinner → six rows (✓/✗ + detail); on failure highlights which gate the seller must fix.

`ActivationPanel`: checklist (verified ✓, passing tests ✓, active credential ✓, card preview loaded) + "Activate seller agent" button → on success shows confetti-free success + link to marketplace + registry discovery URL.

- [ ] **Step 3: server pages** — `(seller-onboarding)/seller/onboarding/<step>/page.tsx`:

Each page: `await consoleSession()` (redirect to `/sign-inWith` handled by group layout) + `await getAgentStep()` from an `actions.ts` that loads the current `onboarding`/`agent` state; render the matching panel; a persistent stepper reads `STEPS` from `lib/onboarding.ts`. `actions.ts` wraps `agent-api.ts` functions, `revalidatePath("/seller/onboarding")` after saves, maps `SellerApiError` to friendly strings for the client.

`/seller/agent/page.tsx` (portal): same components rendered read-mostly: identity block (name/status badge/endpoint path/card link + JSON toggle), instruction textarea (editable), capability grid, policy panel, "Recent test runs" (fetch `/v1/agents/{id}/test` history? — not exposed; show current gate status only), credential status line — **never** raw tokens. Guard: if onboarding incomplete → redirect to `/seller/onboarding`.

- [ ] **Step 4: tests + typecheck**

Run: `cd apps/console && pnpm run test && pnpm run typecheck`
Expected: PASS (add `example-catalog.test.ts` asserting both bundled assets parse + floor ≤ initial ≤ list for every product entry — duplicating just this invariant in TS, no YAML parser needed because the YAML example ships as JSON-first too; the `.yaml` is only human-facing).

- [ ] **Step 5: commit**

```bash
git add apps/console
git commit -m "feat(console): onboarding agent-configuration screens + portal page"
```

---

### Task 8: Acceptance walkthrough + hardening sweep

**Files:**
- Create: `docs/superpowers/plans/2026-11-06-seller-onboarding-walkthrough.md` (checklist) — skip file, inline below
- Modify: `docs/superpowers/specs/2026-11-06-seller-agent-onboarding-design.md` (add "implemented by" line)

- [ ] **Step 1: manual acceptance run** (this validates B.8 gate; do it yourself or pair with the user):

1. `docker compose up verifund registry northwind` and the new shared seller service on `:9205` (add `seller-shared` service to compose **only if** the user wants a demo on this branch; otherwise local `uvicorn seller_agent.__main__:app` with `config_source=shared`).
2. Fresh Clerk user → org → `/seller/onboarding` → complete `integrations` (Import example catalog — verify counts shown = imported) → `agent_setup` (instructions override, capabilities all on) → `policies` (10% cap) → `testing` (all six green) → `activation` (status flips; registry `published=true` via `GET :9100/v1/agents/{id}`).
3. From the marketplace, open discovery; buyer flow shows the agent.
4. Cross-tenant: second org → its agent does **not** see first org's products (expect `SKU not found`-style response or empty catalog list).

- [ ] **Step 2: full verification battery**

Run:
```bash
uv run pytest && uv run ruff check . && cd apps/console && pnpm run typecheck && pnpm run test
```
Expected: all green.

- [ ] **Step 3: onboarding stub pointer**

Append to `docs/superpowers/specs/2026-11-06-seller-agent-onboarding-design.md`:

```markdown
> Implemented by plan `docs/superpowers/plans/2026-11-06-seller-onboarding-agent-configuration.md` (Appendix B of `2026-11-06-single-shared-a2a-endpoint-design.md`).
```

- [ ] **Step 4: final commit**

```bash
git add docs/superpowers/specs/2026-11-06-seller-agent-onboarding-design.md
git commit -m "docs: link onboarding stub to implementation plan"
```

---

## Self-review

**Spec coverage (Appendix B):** B.4.1→ Tasks 5/6/7 (agent_setup, instructions, allowlist). B.4.2→ Tasks 5/7 (policies). B.4.3→ Tasks 4/5/6 (real checks; B.4.3 text matches test-suite). B.4.4→ Tasks 5/7 (activation + card + portal). B.5→ Tasks 5/6 (inline saga, idempotency, compensation notes). B.6→ Tasks 3/4/5/7 (import, example assets, limits, normalized `products`, inventory PK, no catalog hash — nothing tracks catalog hash anywhere). B.7/O18→ Tasks 4/5/6 (minimal runtime slice). B.8→ Tasks 6/8. B.9/O14 divergence kept. B.11 decision O12→ Task 5 409 path; O16→ Task 4 runtime-owned write; O24→ Task 4 `/internal/catalog/import`; O26→ Tasks 1–2/3. Flags: catalog-read path constructs `SellerPolicy` from tables (Task 2 `load_policy`, never YAML per request).
**Gaps found & fixed:** `revoked_credential` test credential needed `revoke_credential_by_raw` — added in Task 5 Step 3. `latest_test_run` for status endpoint — added Task 5 Step 2. Registry publish card needs a builder — `cards.py` added Task 5. Console needs card preview endpoint — `GET /v1/agents/{id}/card` added Task 5 (used by `/seller/agent` and `testing` page). `Idempotency-Key` handled in Task 5 create route.
**Type consistency:** `ConfigUpsert`/`ConfigSnapshot` field names match between Task 2, Task 4, Task 5, Task 6. `parse_catalog_document` returns `list[ImportProduct]` and `ImportProduct.model_dump()` keys match `OrgScopedStore.import_products`'s expected keys (verified against Task 2's `p.get(...)` keys). CP ↔ runtime error contract: 409/422 codes match between Task 4 producer and Task 5 consumer.
