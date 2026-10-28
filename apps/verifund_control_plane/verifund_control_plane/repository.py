from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from verifund_contracts import TransactionState
from verifund_control_plane.db import configure_sqlite, transaction
from verifund_control_plane.domain import TransactionRecord, assert_transition
from verifund_control_plane.errors import VerifundError


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: str | None) -> datetime:
    if not value:
        raise ValueError("missing timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EventInput:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"


@dataclass(frozen=True)
class AuditInput:
    actor: str
    action: str
    note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self._define_tables()

    def _define_tables(self) -> None:
        self.transactions = Table(
            "transactions",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("run_id", String, nullable=False, index=True),
            Column("buyer_id", String, nullable=False),
            Column("seller_id", String, nullable=False, index=True),
            Column("offer_id", String, nullable=False),
            Column("state", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("last_seq", Integer, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("agreement_id", String, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("agreement_version", Integer, nullable=False),
            Column("buyer_agent_review", JSON, nullable=True),
            Column("seller_decision", JSON, nullable=True),
            Column("approval", JSON, nullable=True),
            Column("funding", JSON, nullable=True),
            Column("purchase_order", JSON, nullable=True),
            Column("evidence_summary", JSON, nullable=True),
            Column("verification", JSON, nullable=True),
            Column("payout", JSON, nullable=True),
            Column("receipt", JSON, nullable=True),
            Column("deadlines", JSON, nullable=False),
            Column("last_error", JSON, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.agreements = Table(
            "agreements",
            self.metadata,
            Column("agreement_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.agreement_reviews = Table(
            "agreement_reviews",
            self.metadata,
            Column("review_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("agreement_version", Integer, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("party", String, nullable=False),
            Column("decision", String, nullable=False),
            Column("task_id", String, nullable=False),
            Column("reason_code", String, nullable=True),
            Column("note", String, nullable=False),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("reviewed_at", String, nullable=False),
        )
        self.transaction_events = Table(
            "transaction_events",
            self.metadata,
            Column("transaction_id", String, nullable=False, primary_key=True),
            Column("seq", Integer, nullable=False, primary_key=True),
            Column("type", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("actor", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.ledger = Table(
            "ledger_entries",
            self.metadata,
            Column("entry_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("operation", String, nullable=False),
            Column("account", String, nullable=False),
            Column("debit_cents", Integer, nullable=False),
            Column("credit_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("provider_ref", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.evidence = Table(
            "evidence",
            self.metadata,
            Column("evidence_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("kind", String, nullable=False),
            Column("sha256", String, nullable=False),
            Column("media_type", String, nullable=False),
            Column("size_bytes", Integer, nullable=False),
            Column("original_filename", String, nullable=False),
            Column("note", String, nullable=True),
            Column("captured_at", String, nullable=True),
            Column("created_at", String, nullable=False),
            UniqueConstraint("transaction_id", "sha256", name="uq_evidence_txn_sha"),
        )
        self.provider_operations = Table(
            "provider_operations",
            self.metadata,
            Column("operation_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("kind", String, nullable=False),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("provider_id", String, nullable=True),
            Column("status", String, nullable=False),
            Column("request", JSON, nullable=False),
            Column("response", JSON, nullable=True),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", String, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.webhook_events = Table(
            "webhook_events",
            self.metadata,
            Column("event_id", String, primary_key=True),
            Column("event_type", String, nullable=False),
            Column("resource_id", String, nullable=True),
            Column("payload", JSON, nullable=False),
            Column("payload_hash", String, nullable=False),
            Column("mode", String, nullable=False),
            Column("verified", Integer, nullable=False),
            Column("status", String, nullable=False),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", String, nullable=True),
            Column("received_at", String, nullable=False),
            Column("processed_at", String, nullable=True),
        )
        self.payout_items = Table(
            "payout_items",
            self.metadata,
            Column("item_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("batch_id", String, nullable=False),
            Column("sender_item_id", String, nullable=False, unique=True),
            Column("seller_email", String, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("status", String, nullable=False),
            Column("raw", JSON, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.idempotency = Table(
            "idempotency_keys",
            self.metadata,
            Column("scope", String, nullable=False, primary_key=True),
            Column("key", String, nullable=False, primary_key=True),
            Column("request_hash", String, nullable=False),
            Column("response", JSON, nullable=False),
            Column("status_code", Integer, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.seller_tokens = Table(
            "seller_tokens",
            self.metadata,
            Column("jti_hash", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("scopes", JSON, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("revoked_at", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.checkout_links = Table(
            "checkout_links",
            self.metadata,
            Column("jti", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("kind", String, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("used_at", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.receipts = Table(
            "receipts",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("payload", JSON, nullable=False),
            Column("payload_hash", String, nullable=False),
            Column("signature", String, nullable=False),
            Column("kid", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.audit_log = Table(
            "audit_log",
            self.metadata,
            Column("audit_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("actor", String, nullable=False),
            Column("action", String, nullable=False),
            Column("note", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.reconciler_runs = Table(
            "reconciler_runs",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("started_at", String, nullable=False),
            Column("finished_at", String, nullable=True),
            Column("stats", JSON, nullable=False),
            Column("error", String, nullable=True),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with transaction(self.engine) as conn:
            yield conn

    def _record(self, row: Any) -> TransactionRecord:
        return TransactionRecord(
            transaction_id=row.transaction_id,
            run_id=row.run_id,
            buyer_id=row.buyer_id,
            seller_id=row.seller_id,
            offer_id=row.offer_id,
            state=TransactionState(row.state),
            version=row.version,
            last_seq=row.last_seq,
            amount_cents=row.amount_cents,
            currency=row.currency,
            agreement_id=row.agreement_id,
            agreement_hash=row.agreement_hash,
            agreement_version=row.agreement_version,
            seller_decision=row.seller_decision,
            approval=row.approval,
            funding=row.funding,
            purchase_order=row.purchase_order,
            evidence_summary=row.evidence_summary,
            verification=row.verification,
            payout=row.payout,
            receipt=row.receipt,
            deadlines=row.deadlines,
            last_error=row.last_error,
            created_at=_dt(row.created_at),
            updated_at=_dt(row.updated_at),
        )

    async def count_transactions(self) -> int:
        async with self.engine.connect() as conn:
            result = await conn.execute(select(self.transactions.c.transaction_id))
            return len(result.all())

    async def get_transaction(
        self, transaction_id: str, conn: AsyncConnection | None = None
    ) -> TransactionRecord:
        statement = select(self.transactions).where(
            self.transactions.c.transaction_id == transaction_id
        )
        if conn is not None:
            row = (await conn.execute(statement)).first()
        else:
            async with self.engine.connect() as own_conn:
                row = (await own_conn.execute(statement)).first()
        if row is None:
            raise VerifundError("not_found", "transaction not found", status_code=404)
        return self._record(row)

    async def list_transactions(
        self,
        *,
        run_id: str | None = None,
        state: str | None = None,
        seller_id: str | None = None,
        limit: int = 100,
    ) -> list[TransactionRecord]:
        statement = (
            select(self.transactions)
            .order_by(self.transactions.c.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        if run_id:
            statement = statement.where(self.transactions.c.run_id == run_id)
        if state:
            statement = statement.where(self.transactions.c.state == state)
        if seller_id:
            statement = statement.where(self.transactions.c.seller_id == seller_id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._record(row) for row in rows]

    async def insert_transaction(
        self,
        conn: AsyncConnection,
        txn: TransactionRecord,
        *,
        agreement: dict[str, Any],
        events: list[EventInput],
        audit: AuditInput | None = None,
    ) -> None:
        await conn.execute(
            self.transactions.insert().values(
                transaction_id=txn.transaction_id,
                run_id=txn.run_id,
                buyer_id=txn.buyer_id,
                seller_id=txn.seller_id,
                offer_id=txn.offer_id,
                state=txn.state.value,
                version=txn.version,
                last_seq=len(events),
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                agreement_id=txn.agreement_id,
                agreement_hash=txn.agreement_hash,
                agreement_version=txn.agreement_version,
                seller_decision=txn.seller_decision,
                approval=txn.approval,
                funding=txn.funding,
                purchase_order=txn.purchase_order,
                evidence_summary=txn.evidence_summary,
                verification=txn.verification,
                payout=txn.payout,
                receipt=txn.receipt,
                deadlines=txn.deadlines,
                last_error=txn.last_error,
                created_at=_iso(txn.created_at),
                updated_at=_iso(txn.updated_at),
            )
        )
        await conn.execute(
            self.agreements.insert().values(
                agreement_id=txn.agreement_id,
                transaction_id=txn.transaction_id,
                version=txn.agreement_version,
                payload=agreement,
                agreement_hash=txn.agreement_hash,
                created_at=_iso(txn.created_at),
            )
        )
        for seq, event in enumerate(events, start=1):
            await conn.execute(
                self.transaction_events.insert().values(
                    transaction_id=txn.transaction_id,
                    seq=seq,
                    type=event.type,
                    payload=event.payload,
                    actor=event.actor,
                    created_at=_iso(txn.created_at),
                )
            )
        if audit is not None:
            await self.audit(conn, txn.transaction_id, audit)

    async def transition(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        expected_state: TransactionState,
        new_state: TransactionState,
        changes: dict[str, Any] | None = None,
        events: list[EventInput] | None = None,
        ledger_entries: list[dict[str, Any]] | None = None,
        audit: AuditInput | None = None,
    ) -> TransactionRecord:
        current = await self.get_transaction(transaction_id, conn)
        if current.version != expected_version or current.state != expected_state:
            raise VerifundError(
                "conflict", "transaction changed; reload and retry", status_code=409
            )
        assert_transition(expected_state, new_state)
        return await self._write(
            conn,
            current,
            new_state,
            changes or {},
            events or [],
            ledger_entries or [],
            audit,
        )

    async def update_transaction(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        changes: dict[str, Any],
        events: list[EventInput] | None = None,
        ledger_entries: list[dict[str, Any]] | None = None,
        audit: AuditInput | None = None,
    ) -> TransactionRecord:
        current = await self.get_transaction(transaction_id, conn)
        if current.version != expected_version:
            raise VerifundError(
                "conflict", "transaction changed; reload and retry", status_code=409
            )
        return await self._write(
            conn,
            current,
            current.state,
            changes,
            events or [],
            ledger_entries or [],
            audit,
        )

    async def _write(
        self,
        conn: AsyncConnection,
        current: TransactionRecord,
        new_state: TransactionState,
        changes: dict[str, Any],
        events: list[EventInput],
        ledger_entries: list[dict[str, Any]],
        audit: AuditInput | None,
    ) -> TransactionRecord:
        now = datetime.now(UTC)
        new_version = current.version + 1
        new_seq = current.last_seq + len(events)
        values = {
            **changes,
            "state": new_state.value,
            "version": new_version,
            "last_seq": new_seq,
            "updated_at": _iso(now),
        }
        result = await conn.execute(
            self.transactions.update()
            .where(
                self.transactions.c.transaction_id == current.transaction_id,
                self.transactions.c.version == current.version,
                self.transactions.c.state == current.state.value,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise VerifundError(
                "conflict", "transaction changed; reload and retry", status_code=409
            )
        for offset, event in enumerate(events, start=1):
            await conn.execute(
                self.transaction_events.insert().values(
                    transaction_id=current.transaction_id,
                    seq=current.last_seq + offset,
                    type=event.type,
                    payload=event.payload,
                    actor=event.actor,
                    created_at=_iso(now),
                )
            )
        for entry in ledger_entries:
            await conn.execute(
                self.ledger.insert().values(
                    entry_id=f"le_{uuid.uuid4().hex}",
                    transaction_id=current.transaction_id,
                    operation=entry["operation"],
                    account=entry["account"],
                    debit_cents=int(entry["debit_cents"]),
                    credit_cents=int(entry["credit_cents"]),
                    currency=current.currency,
                    provider_ref=entry.get("provider_ref"),
                    created_at=_iso(now),
                )
            )
        if audit is not None:
            await self.audit(conn, current.transaction_id, audit)
        return await self.get_transaction(current.transaction_id, conn)

    async def append_event(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        event: EventInput,
    ) -> TransactionRecord:
        return await self.update_transaction(
            conn,
            transaction_id,
            expected_version=expected_version,
            changes={},
            events=[event],
        )

    async def events(
        self, transaction_id: str, *, after_seq: int = 0
    ) -> list[dict[str, Any]]:
        statement = (
            select(self.transaction_events)
            .where(self.transaction_events.c.transaction_id == transaction_id)
            .where(self.transaction_events.c.seq > after_seq)
            .order_by(self.transaction_events.c.seq)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [
            {
                "seq": row.seq,
                "type": row.type,
                "payload": row.payload,
                "actor": row.actor,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def get_idempotency(
        self, scope: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        statement = select(self.idempotency).where(
            self.idempotency.c.scope == scope, self.idempotency.c.key == key
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            return None
        if row.request_hash != request_hash:
            raise VerifundError(
                "conflict",
                "idempotency key reused with a different body",
                status_code=409,
            )
        return row.response

    async def put_idempotency(
        self,
        conn: AsyncConnection,
        scope: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        statement = (
            sqlite_insert(self.idempotency)
            .values(
                scope=scope,
                key=key,
                request_hash=request_hash,
                response=response,
                status_code=status_code,
                created_at=_iso(datetime.now(UTC)),
            )
            .on_conflict_do_nothing(index_elements=["scope", "key"])
        )
        await conn.execute(statement)

    async def audit(
        self, conn: AsyncConnection, transaction_id: str, audit: AuditInput
    ) -> None:
        await conn.execute(
            self.audit_log.insert().values(
                audit_id=f"aud_{uuid.uuid4().hex}",
                transaction_id=transaction_id,
                actor=audit.actor,
                action=audit.action,
                note=audit.note,
                payload=audit.payload,
                created_at=_iso(datetime.now(UTC)),
            )
        )
