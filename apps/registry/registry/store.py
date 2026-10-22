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

    async def discover(
        self,
        category: str,
        extension_uri: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for seller in await self.list_sellers():
            if category not in seller["categories"]:
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
