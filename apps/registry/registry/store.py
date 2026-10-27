from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from commerce_core.cards import DEFAULT_CARD_HOSTS
from commerce_core.db import configure_sqlite
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    MetaData,
    String,
    Table,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


class RegistryStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self.metadata = MetaData()
        self.sellers = Table(
            "sellers",
            self.metadata,
            Column("seller_id", String(64), primary_key=True),
            Column("name", String, nullable=False),
            Column("card_url", String, nullable=False),
            Column("categories", JSON, nullable=False),
            Column("card_json", JSON, nullable=False),
            Column("card_hash", String(64), nullable=False),
            Column("last_seen_at", String, nullable=False),
            Column("healthy", Boolean, nullable=False, default=True),
            Column("last_error", String, nullable=True),
        )
        self.listings = Table(
            "seller_listings",
            self.metadata,
            Column("seller_id", String(64), primary_key=True),
            Column("sku", String(128), primary_key=True),
            Column("category", String(128), nullable=False),
            Column("listing_json", JSON, nullable=False),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def upsert(
        self,
        *,
        seller_id: str,
        name: str,
        card_url: str,
        categories: list[str],
        card_json: dict[str, Any],
        card_hash: str,
        healthy: bool,
        error: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        values = {
            "seller_id": seller_id,
            "name": name,
            "card_url": card_url,
            "categories": categories,
            "card_json": card_json,
            "card_hash": card_hash,
            "last_seen_at": now,
            "healthy": healthy,
            "last_error": error,
        }
        statement = sqlite_insert(self.sellers).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["seller_id"],
            set_={
                key: value
                for key, value in values.items()
                if key != "seller_id"
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)
        return values

    async def list_sellers(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.sellers).order_by(self.sellers.c.seller_id)
            )
            return [dict(row._mapping) for row in result]

    async def get(self, seller_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.sellers).where(
                    self.sellers.c.seller_id == seller_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def replace_listings(
        self, seller_id: str, listings: list[dict[str, Any]]
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.listings.delete().where(self.listings.c.seller_id == seller_id)
            )
            if listings:
                await conn.execute(
                    self.listings.insert(),
                    [
                        {
                            "seller_id": seller_id,
                            "sku": item["sku"],
                            "category": item["category"],
                            "listing_json": item,
                        }
                        for item in listings
                    ],
                )

    async def search_listings(
        self, *, category: str | None = None, query: str | None = None,
        sku: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                self.listings.c.listing_json,
                self.sellers.c.seller_id,
                self.sellers.c.name.label("seller_name"),
                self.sellers.c.card_url,
                self.sellers.c.healthy,
            )
            .join(self.sellers, self.sellers.c.seller_id == self.listings.c.seller_id)
            .where(self.sellers.c.healthy.is_(True))
            .order_by(self.listings.c.sku, self.sellers.c.name)
            .limit(max(1, min(limit, 500)))
        )
        if category:
            statement = statement.where(self.listings.c.category == category)
        if sku:
            statement = statement.where(self.listings.c.sku == sku)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            rows = [
                {
                    **row.listing_json,
                    "seller_id": row.seller_id,
                    "seller_name": row.seller_name,
                    "card_url": row.card_url,
                    "healthy": row.healthy,
                }
                for row in result
            ]
        if query:
            needle = query.casefold()
            rows = [
                row for row in rows
                if needle in " ".join(
                    str(row.get(key, "")) for key in ("name", "sku", "description", "category", "seller_name")
                ).casefold()
            ]
        return rows

    async def discover(
        self,
        category: str,
        extension_uri: str,
        limit: int = 20,
        product_sku: str | None = None,
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        listing_sellers = None
        if product_sku:
            async with self.engine.connect() as conn:
                rows = await conn.execute(
                    select(self.listings.c.seller_id).where(
                        self.listings.c.sku == product_sku
                    )
                )
                listing_sellers = {row.seller_id for row in rows}
        for seller in await self.list_sellers():
            if not product_sku and category not in seller["categories"]:
                continue
            if listing_sellers is not None and seller["seller_id"] not in listing_sellers:
                continue
            extensions = (
                seller["card_json"].get("capabilities", {}).get("extensions", [])
            )
            if not any(
                extension.get("uri") == extension_uri
                for extension in extensions
            ):
                continue
            found.append(seller)
            if len(found) >= limit:
                break
        return found

    async def mark_health(
        self, seller_id: str, healthy: bool, error: str | None
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.sellers.update()
                .where(self.sellers.c.seller_id == seller_id)
                .values(healthy=healthy, last_error=error)
            )


def canonical_card_hash(card_json: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(card_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_allowed_hosts() -> tuple[str, ...]:
    return DEFAULT_CARD_HOSTS


def store_metadata_text() -> str:
    return str(text("SELECT 1"))
