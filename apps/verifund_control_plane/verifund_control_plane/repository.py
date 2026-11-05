from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    select,
    tuple_,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from verifund_contracts import EvidenceItem, TransactionState

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
    return datetime.fromisoformat(value)


def _dt_optional(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


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


@dataclass(frozen=True)
class AgreementReviewInput:
    transaction_id: str
    agreement_version: int
    agreement_hash: str
    party: str
    decision: str
    task_id: str
    note: str
    reason_code: str | None
    idempotency_key: str
    reviewed_at: datetime


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
            Column("cancellation", JSON, nullable=True),
            Column("funding", JSON, nullable=True),
            Column("purchase_order", JSON, nullable=True),
            Column("evidence_summary", JSON, nullable=True),
            Column("verification", JSON, nullable=True),
            Column("dispute", JSON, nullable=True),
            Column("payout", JSON, nullable=True),
            Column("tracker", JSON, nullable=True),
            Column("receipt", JSON, nullable=True),
            Column("deadlines", JSON, nullable=False),
            Column("last_error", JSON, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
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
            Column("requirement_id", String, nullable=True),
            Column("submission_attempt", Integer, nullable=True),
            Column("origin", String, nullable=True),
            Column("attributed_to", String, nullable=True),
            Column("purpose", String, nullable=False, default="requirement"),
            Column("artifact_type", String, nullable=True),
            Column("reference", String, nullable=True),
            Column("agreement_version", Integer, nullable=True),
            Column("scan_status", String, nullable=True),
            UniqueConstraint("transaction_id", "sha256", name="uq_evidence_txn_sha"),
        )
        self.evidence_submissions = Table(
            "evidence_submissions",
            self.metadata,
            Column("submission_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("evidence_id", String, nullable=False, index=True),
            Column("requirement_id", String, nullable=False),
            Column("attempt", Integer, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.requirement_declarations = Table(
            "requirement_declarations",
            self.metadata,
            Column("declaration_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("requirement_id", String, nullable=False),
            Column("attempt", Integer, nullable=False),
            Column("actor", String, nullable=False),
            Column("submission_ids", JSON, nullable=False),
            Column("declared_at", String, nullable=False),
            UniqueConstraint(
                "transaction_id",
                "requirement_id",
                "attempt",
                name="uq_declaration_txn_req_attempt",
            ),
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
        self.buyer_tokens = Table(
            "buyer_tokens",
            self.metadata,
            Column("jti_hash", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("buyer_id", String, nullable=False),
            Column("scopes", JSON, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("revoked_at", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.invitation_tokens = Table(
            "invitation_tokens",
            self.metadata,
            Column("jti_hash", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("scopes", JSON, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("used_at", String, nullable=True),
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
        self.fake_orders = Table(
            "fake_orders",
            self.metadata,
            Column("order_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("status", String, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("payer_action_url", String, nullable=True),
            Column("capture_id", String, nullable=True),
            Column("capture_status", String, nullable=True),
            Column("capture_amount_cents", Integer, nullable=True),
            Column("capture_currency", String, nullable=True),
            Column("raw", JSON, nullable=False),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
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
            # SQLite has no in-place migrations. Existing demo databases get
            # new nullable columns through this idempotent ALTER.
            columns = await conn.exec_driver_sql(
                "PRAGMA table_info(transactions)"
            )
            names = {row[1] for row in columns}
            if "tracker" not in names:
                await conn.exec_driver_sql(
                    "ALTER TABLE transactions ADD COLUMN tracker JSON"
                )

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncConnection, None]:
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
            buyer_agent_review=row.buyer_agent_review,
            seller_decision=row.seller_decision,
            approval=row.approval,
            cancellation=row.cancellation,
            funding=row.funding,
            purchase_order=row.purchase_order,
            evidence_summary=row.evidence_summary,
            verification=row.verification,
            dispute=row.dispute,
            payout=row.payout,
            tracker=row.tracker,
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

    async def list_transactions_keyset(
        self,
        seller_id: str,
        *,
        state: str | None = None,
        created_before: str | None = None,
        id_before: str | None = None,
        limit: int = 50,
    ) -> list[TransactionRecord]:
        statement = select(self.transactions).where(
            self.transactions.c.seller_id == seller_id
        )
        if state:
            statement = statement.where(self.transactions.c.state == state)
        if created_before is not None and id_before is not None:
            statement = statement.where(
                tuple_(
                    self.transactions.c.created_at, self.transactions.c.transaction_id
                )
                < tuple_(created_before, id_before)
            )
        statement = statement.order_by(
            self.transactions.c.created_at.desc(),
            self.transactions.c.transaction_id.desc(),
        ).limit(max(1, min(limit, 200)))
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._record(row) for row in rows]

    async def counts_by_state(self, seller_id: str) -> dict[str, int]:
        statement = (
            select(self.transactions.c.state, func.count())
            .where(self.transactions.c.seller_id == seller_id)
            .group_by(self.transactions.c.state)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return {str(state): int(count) for state, count in rows}

    async def list_evidence_for_transactions(
        self, transaction_ids: list[str]
    ) -> list[tuple[str, EvidenceItem]]:
        """Tagged list of (transaction_id, item) pairs; one query."""
        if not transaction_ids:
            return []
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id.in_(transaction_ids)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [(row.transaction_id, self._evidence(row)) for row in rows]

    async def list_evidence_keyset(
        self,
        seller_id: str,
        *,
        kind: str | None = None,
        requirement_id: str | None = None,
        created_before: str | None = None,
        id_before: str | None = None,
        limit: int = 50,
    ) -> list[tuple[str, EvidenceItem]]:
        """Keyset page of (transaction_id, item) pairs, most recent first."""
        statement = select(self.evidence).where(
            self.evidence.c.seller_id == seller_id
        )
        if kind:
            statement = statement.where(self.evidence.c.kind == kind)
        if requirement_id:
            statement = statement.where(
                self.evidence.c.requirement_id == requirement_id
            )
        if created_before is not None and id_before is not None:
            statement = statement.where(
                tuple_(self.evidence.c.created_at, self.evidence.c.evidence_id)
                < tuple_(created_before, id_before)
            )
        statement = statement.order_by(
            self.evidence.c.created_at.desc(),
            self.evidence.c.evidence_id.desc(),
        ).limit(max(1, min(limit, 200)))
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [(row.transaction_id, self._evidence(row)) for row in rows]

    async def transactions_for_evidence(
        self, transaction_ids: list[str]
    ) -> dict[str, TransactionRecord]:
        if not transaction_ids:
            return {}
        statement = select(self.transactions).where(
            self.transactions.c.transaction_id.in_(transaction_ids)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return {row.transaction_id: self._record(row) for row in rows}

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
                buyer_agent_review=txn.buyer_agent_review,
                seller_decision=txn.seller_decision,
                approval=txn.approval,
                cancellation=txn.cancellation,
                funding=txn.funding,
                purchase_order=txn.purchase_order,
                evidence_summary=txn.evidence_summary,
                verification=txn.verification,
                payout=txn.payout,
                tracker=txn.tracker,
                receipt=txn.receipt,
                deadlines=txn.deadlines,
                last_error=txn.last_error,
                created_at=_iso(txn.created_at),
                updated_at=_iso(txn.updated_at),
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
        self, transaction_id: str, *, after_seq: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        statement = (
            select(self.transaction_events)
            .where(self.transaction_events.c.transaction_id == transaction_id)
            .where(self.transaction_events.c.seq > after_seq)
            .order_by(self.transaction_events.c.seq)
        )
        if limit is not None:
            statement = statement.limit(limit)
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

    async def get_idempotency_on(
        self,
        conn: AsyncConnection,
        scope: str,
        key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        row = (
            await conn.execute(
                select(self.idempotency).where(
                    self.idempotency.c.scope == scope,
                    self.idempotency.c.key == key,
                )
            )
        ).first()
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

    async def add_evidence(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        seller_id: str,
        item: EvidenceItem,
        *,
        captured_at: datetime | None = None,
    ) -> tuple[EvidenceItem, bool]:
        statement = (
            sqlite_insert(self.evidence)
            .values(
                evidence_id=item.evidence_id,
                transaction_id=transaction_id,
                seller_id=seller_id,
                kind=item.kind,
                sha256=item.sha256,
                media_type=item.media_type,
                size_bytes=item.size_bytes,
                original_filename=item.original_filename,
                note=item.note,
                captured_at=_iso(captured_at) if captured_at else None,
                created_at=_iso(item.created_at),
                requirement_id=item.requirement_id,
                submission_attempt=item.submission_attempt,
                origin=item.origin,
                attributed_to=item.attributed_to,
                purpose=item.purpose,
                artifact_type=item.artifact_type,
                reference=item.reference,
                agreement_version=item.agreement_version,
                scan_status=item.scan_status,
            )
            .on_conflict_do_nothing(index_elements=["transaction_id", "sha256"])
        )
        result = await conn.execute(statement)
        if result.rowcount == 1:
            return item, True
        existing = await self.get_evidence_by_sha(
            transaction_id, item.sha256, conn
        )
        return existing, False

    async def get_evidence_by_sha(
        self,
        transaction_id: str,
        sha256: str,
        conn: AsyncConnection | None = None,
    ) -> EvidenceItem:
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id == transaction_id,
            self.evidence.c.sha256 == sha256,
        )
        if conn is not None:
            row = (await conn.execute(statement)).first()
        else:
            async with self.engine.connect() as own_conn:
                row = (await own_conn.execute(statement)).first()
        if row is None:
            raise VerifundError(
                "not_found", "evidence not found", status_code=404
            )
        return self._evidence(row)

    def _evidence(self, row: Any) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=row.evidence_id,
            requirement_id=row.requirement_id,
            kind=row.kind,
            sha256=row.sha256,
            media_type=row.media_type,
            size_bytes=row.size_bytes,
            original_filename=row.original_filename,
            note=row.note,
            origin=row.origin,
            attributed_to=row.attributed_to,
            purpose=row.purpose,
            captured_at=_dt_optional(row.captured_at),
            scan_status=row.scan_status,
            agreement_version=row.agreement_version,
            artifact_type=row.artifact_type,
            reference=row.reference,
            submission_attempt=row.submission_attempt,
            created_at=_dt(row.created_at),
        )

    async def list_evidence(self, transaction_id: str) -> list[EvidenceItem]:
        statement = (
            select(self.evidence)
            .where(self.evidence.c.transaction_id == transaction_id)
            .order_by(self.evidence.c.created_at)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._evidence(row) for row in rows]

    async def get_evidence(
        self, transaction_id: str, evidence_id: str
    ) -> EvidenceItem:
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id == transaction_id,
            self.evidence.c.evidence_id == evidence_id,
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            raise VerifundError(
                "not_found", "evidence not found", status_code=404
            )
        return self._evidence(row)

    async def open_attempt(
        self, conn: AsyncConnection, transaction_id: str, requirement_id: str
    ) -> int:
        """The 1-based attempt number the next upload belongs to.

        The attempt is the count of prior declarations for the requirement
        plus one; a declaration closes its attempt.
        """
        row = (
            await conn.execute(
                select(func.max(self.requirement_declarations.c.attempt)).where(
                    self.requirement_declarations.c.transaction_id == transaction_id,
                    self.requirement_declarations.c.requirement_id == requirement_id,
                )
            )
        ).scalar_one_or_none()
        return int(row or 0) + 1

    async def add_evidence_submission(
        self,
        conn: AsyncConnection,
        *,
        submission_id: str,
        transaction_id: str,
        evidence_id: str,
        requirement_id: str,
        attempt: int,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = created_at or datetime.now(UTC)
        await conn.execute(
            self.evidence_submissions.insert().values(
                submission_id=submission_id,
                transaction_id=transaction_id,
                evidence_id=evidence_id,
                requirement_id=requirement_id,
                attempt=attempt,
                created_at=_iso(now),
            )
        )
        return {
            "submission_id": submission_id,
            "transaction_id": transaction_id,
            "evidence_id": evidence_id,
            "requirement_id": requirement_id,
            "attempt": attempt,
            "created_at": _iso(now),
        }

    async def list_submissions(
        self,
        transaction_id: str,
        requirement_id: str | None = None,
        attempt: int | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(self.evidence_submissions).where(
            self.evidence_submissions.c.transaction_id == transaction_id
        )
        if requirement_id is not None:
            statement = statement.where(
                self.evidence_submissions.c.requirement_id == requirement_id
            )
        if attempt is not None:
            statement = statement.where(self.evidence_submissions.c.attempt == attempt)
        statement = statement.order_by(self.evidence_submissions.c.created_at)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def add_declaration(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        requirement_id: str,
        attempt: int,
        *,
        actor: str,
        submission_ids: list[str],
        declared_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = declared_at or datetime.now(UTC)
        declaration_id = f"decl_{uuid.uuid4().hex}"
        await conn.execute(
            self.requirement_declarations.insert().values(
                declaration_id=declaration_id,
                transaction_id=transaction_id,
                requirement_id=requirement_id,
                attempt=attempt,
                actor=actor,
                submission_ids=list(submission_ids),
                declared_at=_iso(now),
            )
        )
        return {
            "declaration_id": declaration_id,
            "transaction_id": transaction_id,
            "requirement_id": requirement_id,
            "attempt": attempt,
            "actor": actor,
            "submission_ids": list(submission_ids),
            "declared_at": _iso(now),
        }

    async def list_declarations(
        self, transaction_id: str, requirement_id: str | None = None
    ) -> list[dict[str, Any]]:
        statement = select(self.requirement_declarations).where(
            self.requirement_declarations.c.transaction_id == transaction_id
        )
        if requirement_id is not None:
            statement = statement.where(
                self.requirement_declarations.c.requirement_id == requirement_id
            )
        statement = statement.order_by(self.requirement_declarations.c.attempt)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def create_provider_operation(
        self,
        conn: AsyncConnection,
        operation_id: str,
        transaction_id: str,
        kind: str,
        idempotency_key: str,
        request: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        await conn.execute(
            self.provider_operations.insert().values(
                operation_id=operation_id,
                transaction_id=transaction_id,
                kind=kind,
                idempotency_key=idempotency_key,
                provider_id=None,
                status="started",
                request=request,
                response=None,
                attempts=0,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )

    async def update_provider_operation(
        self,
        operation_id: str,
        *,
        status: str,
        provider_id: str | None = None,
        response: dict[str, Any] | None = None,
        last_error: str | None = None,
        increment_attempts: bool = False,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "provider_id": provider_id,
            "response": response,
            "last_error": last_error,
            "updated_at": _iso(datetime.now(UTC)),
        }
        statement = (
            self.provider_operations.update()
            .where(
                self.provider_operations.c.operation_id == operation_id
            )
            .values(**values)
        )
        if increment_attempts:
            statement = statement.values(
                attempts=self.provider_operations.c.attempts + 1
            )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_provider_operation(self, operation_id: str) -> dict[str, Any]:
        statement = select(self.provider_operations).where(
            self.provider_operations.c.operation_id == operation_id
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            raise VerifundError(
                "not_found", "provider operation not found", status_code=404
            )
        return dict(row._mapping)

    async def list_started_operations(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        statement = (
            select(self.provider_operations)
            .where(self.provider_operations.c.status == "started")
            .limit(limit)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [dict(row._mapping) for row in rows]

    async def insert_webhook_event(
        self,
        conn: AsyncConnection,
        event_id: str,
        event_type: str,
        resource_id: str | None,
        payload_hash: str,
        payload: dict[str, Any],
        mode: str,
        verified: bool,
    ) -> bool:
        statement = (
            sqlite_insert(self.webhook_events)
            .values(
                event_id=event_id,
                event_type=event_type,
                resource_id=resource_id,
                payload=payload,
                payload_hash=payload_hash,
                mode=mode,
                verified=1 if verified else 0,
                status="pending",
                attempts=0,
                last_error=None,
                received_at=_iso(datetime.now(UTC)),
                processed_at=None,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await conn.execute(statement)
        return result.rowcount == 1

    async def mark_webhook_event(
        self, event_id: str, status: str, *, last_error: str | None = None
    ) -> None:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": status,
            "last_error": last_error,
            "attempts": self.webhook_events.c.attempts + 1,
            "processed_at": (
                _iso(now) if status in {"processed", "unmatched"} else None
            ),
        }
        async with self.engine.begin() as conn:
            await conn.execute(
                self.webhook_events.update()
                .where(self.webhook_events.c.event_id == event_id)
                .values(**values)
            )

    async def get_webhook_event(self, event_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.webhook_events).where(
                        self.webhook_events.c.event_id == event_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "not_found", "webhook event not found", status_code=404
            )
        return dict(row._mapping)

    async def list_webhook_events(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        statement = (
            select(self.webhook_events)
            .order_by(self.webhook_events.c.received_at)
            .limit(limit)
        )
        if status:
            statement = statement.where(
                self.webhook_events.c.status == status
            )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [dict(row._mapping) for row in rows]

    async def upsert_payout_item(
        self,
        conn: AsyncConnection,
        item_id: str,
        transaction_id: str,
        batch_id: str,
        sender_item_id: str,
        seller_email: str,
        amount_cents: int,
        currency: str,
        status: str,
        raw: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        statement = (
            sqlite_insert(self.payout_items)
            .values(
                item_id=item_id,
                transaction_id=transaction_id,
                batch_id=batch_id,
                sender_item_id=sender_item_id,
                seller_email=seller_email,
                amount_cents=amount_cents,
                currency=currency,
                status=status,
                raw=raw,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["item_id"],
                set_={"status": status, "raw": raw, "updated_at": now},
            )
        )
        await conn.execute(statement)

    async def get_payout_item(self, item_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.payout_items).where(
                        self.payout_items.c.item_id == item_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "not_found", "payout item not found", status_code=404
            )
        return dict(row._mapping)

    async def list_payout_items(
        self, transaction_id: str
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.payout_items)
                    .where(
                        self.payout_items.c.transaction_id == transaction_id
                    )
                    .order_by(self.payout_items.c.created_at)
                )
            ).all()
        return [dict(row._mapping) for row in rows]

    async def save_seller_token(
        self,
        conn: AsyncConnection,
        jti_hash: str,
        transaction_id: str,
        seller_id: str,
        agreement_hash: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.seller_tokens.insert().values(
                jti_hash=jti_hash,
                transaction_id=transaction_id,
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                scopes=scopes,
                expires_at=_iso(expires_at),
                revoked_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def revoke_seller_tokens(
        self, conn: AsyncConnection, transaction_id: str, now: datetime
    ) -> None:
        await conn.execute(
            self.seller_tokens.update()
            .where(
                self.seller_tokens.c.transaction_id == transaction_id,
                self.seller_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=_iso(now))
        )

    async def get_seller_token(self, jti_hash: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.seller_tokens).where(
                        self.seller_tokens.c.jti_hash == jti_hash
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "unauthorized", "seller token is not recognized", status_code=401
            )
        return dict(row._mapping)

    async def save_buyer_token(
        self,
        conn: AsyncConnection,
        *,
        jti_hash: str,
        transaction_id: str,
        buyer_id: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.buyer_tokens.insert().values(
                jti_hash=jti_hash,
                transaction_id=transaction_id,
                buyer_id=buyer_id,
                scopes=scopes,
                expires_at=_iso(expires_at),
                revoked_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def get_buyer_token(self, jti_hash: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.buyer_tokens).where(
                        self.buyer_tokens.c.jti_hash == jti_hash
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "unauthorized", "buyer token is not recognized", status_code=401
            )
        return dict(row._mapping)

    async def revoke_buyer_tokens(
        self, conn: AsyncConnection, transaction_id: str, now: datetime
    ) -> None:
        await conn.execute(
            self.buyer_tokens.update()
            .where(
                self.buyer_tokens.c.transaction_id == transaction_id,
                self.buyer_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=_iso(now))
        )

    async def save_invitation_token(
        self,
        conn: AsyncConnection,
        *,
        jti_hash: str,
        transaction_id: str,
        seller_id: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.invitation_tokens.insert().values(
                jti_hash=jti_hash,
                transaction_id=transaction_id,
                seller_id=seller_id,
                scopes=scopes,
                expires_at=_iso(expires_at),
                used_at=None,
                revoked_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def get_invitation_token(self, jti_hash: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.invitation_tokens).where(
                        self.invitation_tokens.c.jti_hash == jti_hash
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "unauthorized", "invitation token is not recognized", status_code=401
            )
        return dict(row._mapping)

    async def mark_invitation_used(
        self, conn: AsyncConnection, jti_hash: str, now: datetime
    ) -> None:
        await conn.execute(
            self.invitation_tokens.update()
            .where(self.invitation_tokens.c.jti_hash == jti_hash)
            .values(used_at=_iso(now), revoked_at=_iso(now))
        )

    async def revoke_invitation_tokens(
        self, conn: AsyncConnection, transaction_id: str, now: datetime
    ) -> None:
        await conn.execute(
            self.invitation_tokens.update()
            .where(
                self.invitation_tokens.c.transaction_id == transaction_id,
                self.invitation_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=_iso(now))
        )

    async def update_evidence_scan_status(
        self, conn: AsyncConnection, evidence_id: str, status: str
    ) -> None:
        await conn.execute(
            self.evidence.update()
            .where(self.evidence.c.evidence_id == evidence_id)
            .values(scan_status=status)
        )

    async def create_checkout_link(
        self,
        conn: AsyncConnection,
        jti: str,
        transaction_id: str,
        kind: str,
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.checkout_links.insert().values(
                jti=jti,
                transaction_id=transaction_id,
                kind=kind,
                expires_at=_iso(expires_at),
                used_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def get_checkout_link(self, jti: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.checkout_links).where(
                        self.checkout_links.c.jti == jti
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "not_found", "checkout link not found", status_code=404
            )
        return dict(row._mapping)

    async def consume_checkout_link(self, jti: str, now: datetime) -> bool:
        async with self.engine.begin() as conn:
            result = await conn.execute(
                self.checkout_links.update()
                .where(
                    self.checkout_links.c.jti == jti,
                    self.checkout_links.c.used_at.is_(None),
                )
                .values(used_at=_iso(now))
            )
            return result.rowcount == 1

    async def save_receipt(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        payload: dict[str, Any],
        payload_hash: str,
        signature: str,
        kid: str,
    ) -> None:
        statement = (
            sqlite_insert(self.receipts)
            .values(
                transaction_id=transaction_id,
                payload=payload,
                payload_hash=payload_hash,
                signature=signature,
                kid=kid,
                created_at=_iso(datetime.now(UTC)),
            )
            .on_conflict_do_update(
                index_elements=["transaction_id"],
                set_={
                    "payload": payload,
                    "payload_hash": payload_hash,
                    "signature": signature,
                    "kid": kid,
                },
            )
        )
        await conn.execute(statement)

    async def get_receipt(self, transaction_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.receipts).where(
                        self.receipts.c.transaction_id == transaction_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "not_found", "receipt not available", status_code=404
            )
        return dict(row._mapping)

    async def save_reconciler_run(
        self,
        run_id: str,
        started_at: datetime,
        finished_at: datetime | None,
        stats: dict[str, Any],
        error: str | None = None,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.reconciler_runs.insert().values(
                    run_id=run_id,
                    started_at=_iso(started_at),
                    finished_at=(
                        _iso(finished_at) if finished_at else None
                    ),
                    stats=stats,
                    error=error,
                )
            )

    async def list_reconciler_runs(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.reconciler_runs)
                    .order_by(self.reconciler_runs.c.started_at.desc())
                    .limit(limit)
                )
            ).all()
        return [dict(row._mapping) for row in rows]

    async def ledger_balances(self, transaction_id: str) -> dict[str, int]:
        rows = await self.ledger_entries(transaction_id)
        balances = {"held_funds": 0, "platform_cash": 0, "seller_paid": 0}
        for row in rows:
            account = row["account"]
            if account == "platform_cash":
                balances[account] += row["debit_cents"] - row["credit_cents"]
            else:
                balances[account] += row["credit_cents"] - row["debit_cents"]
        return balances

    async def ledger_entries(
        self, transaction_id: str
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.ledger)
                    .where(self.ledger.c.transaction_id == transaction_id)
                    .order_by(self.ledger.c.created_at)
                )
            ).all()
        return [dict(row._mapping) for row in rows]

    async def save_fake_order(
        self,
        conn: AsyncConnection,
        *,
        order_id: str,
        transaction_id: str,
        status: str,
        amount_cents: int,
        currency: str,
        payer_action_url: str | None,
        raw: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        await conn.execute(
            self.fake_orders.insert().values(
                order_id=order_id,
                transaction_id=transaction_id,
                status=status,
                amount_cents=amount_cents,
                currency=currency,
                payer_action_url=payer_action_url,
                capture_id=None,
                capture_status=None,
                capture_amount_cents=None,
                capture_currency=None,
                raw=raw,
                created_at=now,
                updated_at=now,
            )
        )

    async def get_fake_order(self, order_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.fake_orders).where(
                        self.fake_orders.c.order_id == order_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError("not_found", "fake order not found", status_code=404)
        return dict(row._mapping)

    async def update_fake_order(
        self, conn: AsyncConnection, order_id: str, **changes: Any
    ) -> None:
        await conn.execute(
            self.fake_orders.update()
            .where(self.fake_orders.c.order_id == order_id)
            .values(**changes, updated_at=_iso(datetime.now(UTC)))
        )

    async def find_transaction_by_order_id(
        self, order_id: str
    ) -> TransactionRecord | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.transactions).where(
                        self.transactions.c.funding.is_not(None)
                    )
                )
            ).all()
        for row in rows:
            if str((row.funding or {}).get("provider_order_id") or "") == order_id:
                return self._record(row)
        return None

    async def find_transaction_by_capture_id(
        self, capture_id: str
    ) -> TransactionRecord | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.transactions).where(
                        self.transactions.c.funding.is_not(None)
                    )
                )
            ).all()
        for row in rows:
            if str((row.funding or {}).get("capture_id") or "") == capture_id:
                return self._record(row)
        return None

    async def find_payout_transaction(self, batch_id: str) -> str | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.payout_items).where(
                        self.payout_items.c.batch_id == batch_id
                    )
                )
            ).first()
        return str(row.transaction_id) if row is not None else None

    async def find_started_operation(
        self, transaction_id: str, kind: str
    ) -> dict[str, Any] | None:
        statement = select(self.provider_operations).where(
            self.provider_operations.c.transaction_id == transaction_id,
            self.provider_operations.c.kind == kind,
            self.provider_operations.c.status == "started",
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        return dict(row._mapping) if row is not None else None
