from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

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
        offer_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,
        offer_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (organization_id, offer_id)
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
