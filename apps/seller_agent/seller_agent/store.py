from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from commerce_core.contracts import Offer, Order
from commerce_core.db import configure_sqlite
from commerce_core.pricing import SellerPolicy
from sqlalchemy import (
    JSON,
    Column,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@dataclass(frozen=True)
class Stock:
    on_hand: int
    incoming: int
    incoming_days: int | None = None



@dataclass(frozen=True)
class Reservation:
    split_shipment: bool


class SellerTransaction:
    def __init__(self, store: SellerStore, conn: AsyncConnection) -> None:
        self.store = store
        self.conn = conn

    async def get_offer(self, offer_id: str) -> Offer | None:
        result = await self.conn.execute(
            select(self.store.offers).where(
                self.store.offers.c.offer_id == offer_id
            )
        )
        row = result.first()
        return Offer.model_validate(row.offer_json) if row else None

    async def get_order_by_idempotency(self, key: str) -> Order | None:
        result = await self.conn.execute(
            select(self.store.orders).where(
                self.store.orders.c.idempotency_key == key
            )
        )
        row = result.first()
        return Order.model_validate(row.order_json) if row else None

    async def reserve(
        self, sku: str, quantity: int, *, allow_split: bool
    ) -> Reservation:
        result = await self.conn.execute(
            select(self.store.inventory).where(
                self.store.inventory.c.sku == sku
            )
        )
        row = result.first()
        if row is None:
            raise ValueError("unknown sku")
        if row.on_hand >= quantity:
            await self.conn.execute(
                self.store.inventory.update()
                .where(self.store.inventory.c.sku == sku)
                .values(on_hand=row.on_hand - quantity)
            )
            return Reservation(split_shipment=False)
        if (
            allow_split
            and row.on_hand + row.incoming >= quantity
            and (row.incoming_days is None or row.incoming_days <= 14)
        ):
            remaining = row.on_hand + row.incoming - quantity
            await self.conn.execute(
                self.store.inventory.update()
                .where(self.store.inventory.c.sku == sku)
                .values(on_hand=0, incoming=remaining)
            )
            return Reservation(split_shipment=True)
        raise ValueError("out_of_stock")

    async def save_order(self, order: Order, *, idempotency_key: str) -> None:
        await self.conn.execute(
            self.store.orders.insert().values(
                order_id=order.order_id,
                offer_id=order.offer_id,
                seller_id=order.seller_id,
                idempotency_key=idempotency_key,
                order_json=order.model_dump(mode="json"),
                created_at=datetime.now(UTC).isoformat(),
            )
        )


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

        self.seller_agreement_reviews = Table(
            "seller_agreement_reviews",
            self.metadata,
            Column("agreement_id", String, nullable=False),
            Column("version", Integer, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("offer_hash", String, nullable=False),
            Column("terms", String, nullable=False),
            Column("change_request_id", String, nullable=True),
            Column("decision", String, nullable=False),
            Column("reviewed_at", String, nullable=False),
            Column("task_id", String, nullable=False),
            Column("context_id", String, nullable=False),
            UniqueConstraint("agreement_id", "version", name="pk_seller_agreement_reviews"),
        )

        self.settlement_tokens = Table(
            "settlement_tokens",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("seller_id", String, nullable=False),
            Column("token", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.evidence_outbox = Table(
            "evidence_outbox",
            self.metadata,
            Column("evidence_key", String, primary_key=True),
            Column("transaction_id", String, nullable=False),
            Column("seller_id", String, nullable=False),
            # Legacy ``kind`` values are preserved for back-compat; new rows
            # mirror the CP ``requirement_id`` into both columns so the
            # historic unique constraint keeps deduplicating.
            Column("kind", String, nullable=False),
            Column("requirement_id", String, nullable=True),
            Column("filename", String, nullable=False),
            Column("media_type", String, nullable=False),
            Column("content", LargeBinary, nullable=False),
            Column("note", String, nullable=False, default=""),
            Column("captured_at", String, nullable=True),
            Column("status", String, nullable=False, default="pending"),
            Column("attempts", Integer, nullable=False, default=0),
            Column("next_attempt_at", String, nullable=False),
            Column("last_error", String, nullable=True),
            Column("created_at", String, nullable=False),
            Column("sent_at", String, nullable=True),
            UniqueConstraint(
                "transaction_id",
                "kind",
                name="uq_evidence_outbox_transaction_kind",
            ),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)
        await self._migrate_evidence_outbox()

    async def _migrate_evidence_outbox(self) -> None:
        """Add ``requirement_id`` to pre-migration databases and backfill it.

        Fresh databases already have the column via ``create_all``. Existing
        SQLite databases only gain it through this idempotent migration.
        """
        from sqlalchemy import inspect, text

        async with self.engine.begin() as conn:
            inspector = await conn.run_sync(
                lambda sync_conn: (
                    inspect(sync_conn).get_columns("evidence_outbox")
                )
            )
            columns = {col["name"] for col in inspector}
            if "requirement_id" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE evidence_outbox "
                        "ADD COLUMN requirement_id TEXT"
                    )
                )
            if "kind" in columns:
                await conn.execute(
                    text(
                        "UPDATE evidence_outbox SET requirement_id = kind "
                        "WHERE requirement_id IS NULL"
                    )
                )

    async def seed_catalog(self, policy: SellerPolicy) -> None:
        for product in policy.catalog():
            statement = sqlite_insert(self.inventory).values(
                sku=product.sku,
                on_hand=product.stock_on_hand,
                incoming=product.incoming_stock,
                incoming_days=product.incoming_days,
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=["sku"]
            )
            async with self.engine.begin() as conn:
                await conn.execute(statement)

    @asynccontextmanager
    async def transaction(self):
        async with self.engine.begin() as conn:
            yield SellerTransaction(self, conn)

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

    async def list_offers(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.offers)
                .order_by(self.offers.c.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
            return [
                {
                    "created_at": row.created_at,
                    "offer": Offer.model_validate(row.offer_json).model_dump(
                        mode="json"
                    ),
                }
                for row in result
            ]

    async def list_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.orders)
                .order_by(self.orders.c.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
            return [
                {
                    "created_at": row.created_at,
                    "order": Order.model_validate(row.order_json).model_dump(
                        mode="json"
                    ),
                }
                for row in result
            ]

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

    async def get_latest_offer(self, task_id: str) -> Offer | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.offers)
                .where(self.offers.c.task_id == task_id)
                .order_by(self.offers.c.created_at.desc())
                .limit(1)
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

    async def save_settlement_token(
        self, transaction_id: str, seller_id: str, token: str
    ) -> None:
        await save_settlement_token(self, transaction_id, seller_id, token)

    async def get_settlement_token(self, transaction_id: str) -> str | None:
        return await get_settlement_token(self, transaction_id)

    async def save_settlement_context(
        self, *, transaction_id: str, seller_id: str
    ) -> None:
        """Record a transaction as a known settlement without a secret.

        The control plane migrated routes authenticate with the shared
        internal token + org/seller context, so no bearer token is stored.
        """
        await save_settlement_context(
            self, transaction_id=transaction_id, seller_id=seller_id
        )

    async def enqueue_evidence(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str | None = None,
        requirement_id: str | None = None,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        resolved = requirement_id or kind
        if not resolved:
            raise ValueError("requirement_id is required")
        return await enqueue_evidence(
            self,
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=resolved,
            requirement_id=resolved,
            content=content,
            media_type=media_type,
            filename=filename,
            note=note,
            captured_at=captured_at,
            created_at=created_at,
        )

    async def list_due_evidence(
        self, *, now: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await list_due_evidence(self, now=now, limit=limit)

    async def mark_evidence_sent(self, evidence_key: str, *, sent_at: str) -> None:
        await mark_evidence_sent(self, evidence_key, sent_at=sent_at)

    async def reschedule_evidence(
        self, evidence_key: str, *, next_attempt_at: str, error: str
    ) -> None:
        await reschedule_evidence(
            self,
            evidence_key,
            next_attempt_at=next_attempt_at,
            error=error,
        )

    async def fail_evidence(self, evidence_key: str, *, error: str) -> None:
        await fail_evidence(self, evidence_key, error=error)

    async def get_evidence_outbox(
        self, transaction_id: str, kind: str
    ) -> dict[str, Any] | None:
        return await get_evidence_outbox(self, transaction_id, kind)

    async def list_settlement_tokens(
        self, limit: int = 5
    ) -> list[dict[str, Any]]:
        return await list_settlement_tokens(self, limit)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def save_settlement_token(self, transaction_id: str, seller_id: str, token: str) -> None:
    statement = sqlite_insert(self.settlement_tokens).values(
        transaction_id=transaction_id,
        seller_id=seller_id,
        token=token,
        updated_at=_iso(datetime.now(UTC)),
    )
    statement = statement.on_conflict_do_update(
        index_elements=["transaction_id"],
        set_={
            "seller_id": seller_id,
            "token": token,
            "updated_at": _iso(datetime.now(UTC)),
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(statement)


async def get_settlement_token(self, transaction_id: str) -> str | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(self.settlement_tokens.c.token).where(
                self.settlement_tokens.c.transaction_id == transaction_id
            )
        )
        row = result.first()
        return row.token if row else None


async def save_settlement_context(
    self, *, transaction_id: str, seller_id: str
) -> None:
    statement = sqlite_insert(self.settlement_tokens).values(
        transaction_id=transaction_id,
        seller_id=seller_id,
        token="",
        updated_at=_iso(datetime.now(UTC)),
    )
    statement = statement.on_conflict_do_update(
        index_elements=["transaction_id"],
        set_={
            "seller_id": seller_id,
            "updated_at": _iso(datetime.now(UTC)),
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(statement)


async def enqueue_evidence(
    self,
    *,
    transaction_id: str,
    seller_id: str,
    kind: str,
    requirement_id: str | None = None,
    content: bytes,
    media_type: str,
    filename: str,
    note: str = "",
    captured_at: str | None = None,
    created_at: datetime | None = None,
) -> bool:
    resolved = requirement_id or kind
    created = _iso(created_at or datetime.now(UTC))
    statement = (
        sqlite_insert(self.evidence_outbox)
        .values(
            evidence_key=uuid.uuid4().hex,
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=resolved,
            requirement_id=resolved,
            filename=filename,
            media_type=media_type,
            content=content,
            note=note,
            captured_at=captured_at,
            status="pending",
            attempts=0,
            next_attempt_at=created,
            last_error=None,
            created_at=created,
            sent_at=None,
        )
        .on_conflict_do_nothing(
            index_elements=["transaction_id", "kind"]
        )
    )
    async with self.engine.begin() as conn:
        result = await conn.execute(statement)
    return bool(result.rowcount)


async def list_due_evidence(self, *, now: str, limit: int = 20) -> list[dict[str, Any]]:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(self.evidence_outbox)
            .where(
                self.evidence_outbox.c.status == "pending",
                self.evidence_outbox.c.next_attempt_at <= now,
            )
            .order_by(self.evidence_outbox.c.created_at)
            .limit(max(1, min(limit, 100)))
        )
        return [dict(row._mapping) for row in result]


async def mark_evidence_sent(self, evidence_key: str, *, sent_at: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            self.evidence_outbox.update()
            .where(self.evidence_outbox.c.evidence_key == evidence_key)
            .values(status="sent", sent_at=sent_at, last_error=None)
        )


async def reschedule_evidence(
    self,
    evidence_key: str,
    *,
    next_attempt_at: str,
    error: str,
) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            self.evidence_outbox.update()
            .where(self.evidence_outbox.c.evidence_key == evidence_key)
            .values(
                attempts=self.evidence_outbox.c.attempts + 1,
                next_attempt_at=next_attempt_at,
                last_error=error,
            )
        )


async def fail_evidence(self, evidence_key: str, *, error: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            self.evidence_outbox.update()
            .where(self.evidence_outbox.c.evidence_key == evidence_key)
            .values(
                status="failed",
                attempts=self.evidence_outbox.c.attempts + 1,
                last_error=error,
            )
        )


async def get_evidence_outbox(self, transaction_id: str, kind: str) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(self.evidence_outbox).where(
                self.evidence_outbox.c.transaction_id == transaction_id,
                self.evidence_outbox.c.kind == kind,
            )
        )
        row = result.first()
        return dict(row._mapping) if row else None

async def list_settlement_tokens(self, limit: int = 5) -> list[dict[str, Any]]:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(
                self.settlement_tokens.c.transaction_id,
                self.settlement_tokens.c.seller_id,
                self.settlement_tokens.c.updated_at,
            )
            .order_by(self.settlement_tokens.c.updated_at.desc())
            .limit(max(1, min(limit, 20)))
        )
        return [dict(row._mapping) for row in result]

