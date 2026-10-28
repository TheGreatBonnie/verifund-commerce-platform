from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from commerce_core.db import configure_sqlite
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from buyer_agent.settlement_store_base import isoformat


class SettlementStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self.secrets = Table(
            "run_secrets",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("run_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("purpose", String, nullable=False),
            Column("seller_token", String, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.projections = Table(
            "settlement_projections",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("last_seq", Integer, nullable=False),
            Column("updated_at", String, nullable=False),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def save_secret(
        self,
        *,
        run_id: str,
        transaction_id: str,
        seller_id: str,
        purpose: str,
        token: str | None = None,
        seller_token: str | None = None,
        expires_at: datetime,
    ) -> None:
        resolved = seller_token if seller_token is not None else token
        if resolved is None:
            raise ValueError("token is required")
        statement = sqlite_insert(self.secrets).values(
            transaction_id=transaction_id,
            run_id=run_id,
            seller_id=seller_id,
            purpose=purpose,
            seller_token=resolved,
            expires_at=isoformat(expires_at),
            created_at=isoformat(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "run_id": run_id,
                "seller_id": seller_id,
                "purpose": purpose,
                "seller_token": resolved,
                "expires_at": isoformat(expires_at),
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_secret(
        self, run_id: str, transaction_id: str, purpose: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.secrets).where(
                    self.secrets.c.run_id == run_id,
                    self.secrets.c.transaction_id == transaction_id,
                    self.secrets.c.purpose == purpose,
                )
            )).first()
        return dict(row._mapping) if row is not None else None

    async def get_secret_by_transaction(
        self, transaction_id: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.secrets).where(
                    self.secrets.c.transaction_id == transaction_id
                )
            )).first()
        return dict(row._mapping) if row is not None else None

    async def delete_secret(self, transaction_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.secrets.delete().where(
                    self.secrets.c.transaction_id == transaction_id
                )
            )

    async def save_projection(
        self, run_id: str, projection: dict[str, Any]
    ) -> bool:
        last_seq = int(projection.get("last_seq") or 0)
        statement = sqlite_insert(self.projections).values(
            run_id=run_id,
            transaction_id=str(projection["transaction_id"]),
            payload=projection,
            last_seq=last_seq,
            updated_at=isoformat(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["run_id"],
            set_={
                "transaction_id": str(projection["transaction_id"]),
                "payload": projection,
                "last_seq": last_seq,
                "updated_at": isoformat(datetime.now(UTC)),
            },
            where=self.projections.c.last_seq < last_seq,
        )
        async with self.engine.begin() as conn:
            result = await conn.execute(statement)
        return result.rowcount == 1

    async def get_projection(self, run_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.projections).where(
                    self.projections.c.run_id == run_id
                )
            )).first()
        return dict(row.payload) if row is not None else None