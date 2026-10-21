from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from commerce_core.contracts import Offer, Order
from commerce_core.db import configure_sqlite
from commerce_core.pricing import SellerPolicy


@dataclass(frozen=True)
class Stock:
    on_hand: int
    incoming: int
    incoming_days: int | None = None


class SellerStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self.inventory = Table(
            "inventory",
            self.metadata,
            Column("sku", String, primary_key=True),
            Column("on_hand", Integer, nullable=False),
            Column("incoming", Integer, nullable=False, default=0),
            Column("incoming_days", Integer, nullable=True),
        )
        self.offers = Table(
            "offers",
            self.metadata,
            Column("offer_id", String, primary_key=True),
            Column("task_id", String, nullable=False),
            Column("context_id", String, nullable=False),
            Column("seller_id", String, nullable=False),
            Column("offer_json", JSON, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.orders = Table(
            "orders",
            self.metadata,
            Column("order_id", String, primary_key=True),
            Column("offer_id", String, nullable=False),
            Column("seller_id", String, nullable=False),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("order_json", JSON, nullable=False),
            Column("created_at", String, nullable=False),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def seed_catalog(self, policy: SellerPolicy) -> None:
        statement = sqlite_insert(self.inventory).values(
            sku=policy.sku,
            on_hand=policy.stock_on_hand,
            incoming=policy.incoming_stock,
            incoming_days=policy.incoming_days,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["sku"]
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_stock(self, sku: str) -> Stock:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.inventory).where(self.inventory.c.sku == sku)
            )
            row = result.first()
            if row is None:
                return Stock(0, 0, None)
            return Stock(
                on_hand=row.on_hand,
                incoming=row.incoming,
                incoming_days=row.incoming_days,
            )

    async def set_stock(
        self,
        sku: str,
        on_hand: int,
        incoming: int,
        incoming_days: int | None = None,
    ) -> None:
        values = {
            "sku": sku,
            "on_hand": on_hand,
            "incoming": incoming,
            "incoming_days": incoming_days,
        }
        statement = sqlite_insert(self.inventory).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["sku"],
            set_={
                "on_hand": on_hand,
                "incoming": incoming,
                "incoming_days": incoming_days,
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def save_offer(
        self, offer: Offer, *, task_id: str, context_id: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                sqlite_insert(self.offers)
                .values(
                    offer_id=offer.offer_id,
                    task_id=task_id,
                    context_id=context_id,
                    seller_id=offer.seller_id,
                    offer_json=offer.model_dump(mode="json"),
                    created_at=datetime.now(UTC).isoformat(),
                )
                .on_conflict_do_update(
                    index_elements=["offer_id"],
                    set_={
                        "offer_json": offer.model_dump(mode="json"),
                    },
                )
            )

    async def get_offer(self, offer_id: str) -> Offer | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.offers).where(self.offers.c.offer_id == offer_id)
            )
            row = result.first()
            if row is None:
                return None
            return Offer.model_validate(row.offer_json)

    async def save_order(
        self,
        order: Order,
        *,
        idempotency_key: str,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.orders.insert().values(
                    order_id=order.order_id,
                    offer_id=order.offer_id,
                    seller_id=order.seller_id,
                    idempotency_key=idempotency_key,
                    order_json=order.model_dump(mode="json"),
                    created_at=datetime.now(UTC).isoformat(),
                )
            )

    async def get_order_by_idempotency(
        self, idempotency_key: str
    ) -> Order | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.orders).where(
                    self.orders.c.idempotency_key == idempotency_key
                )
            )
            row = result.first()
            if row is None:
                return None
            return Order.model_validate(row.order_json)

    async def reserve(
        self,
        sku: str,
        quantity: int,
        *,
        allow_split: bool,
    ) -> dict[str, Any]:
        async with self.engine.begin() as conn:
            result = await conn.execute(
                select(self.inventory).where(self.inventory.c.sku == sku)
            )
            row = result.first()
            if row is None:
                raise ValueError("unknown sku")
            if row.on_hand >= quantity:
                await conn.execute(
                    self.inventory.update()
                    .where(self.inventory.c.sku == sku)
                    .values(on_hand=row.on_hand - quantity)
                )
                return {"split_shipment": False, "on_hand": row.on_hand - quantity}
            if (
                allow_split
                and row.on_hand + row.incoming >= quantity
                and (row.incoming_days is None or row.incoming_days <= 14)
            ):
                remaining = row.on_hand + row.incoming - quantity
                await conn.execute(
                    self.inventory.update()
                    .where(self.inventory.c.sku == sku)
                    .values(on_hand=0, incoming=remaining)
                )
                return {"split_shipment": True, "on_hand": 0}
            raise ValueError("out_of_stock")
