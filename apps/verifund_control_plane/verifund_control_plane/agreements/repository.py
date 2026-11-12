from __future__ import annotations

import json as _json_mod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, overload

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from verifund_contracts.models import AgreementDecision, AgreementState

from verifund_control_plane.db import transaction as _engine_transaction

from .models import (
    Agreement,
    AgreementDecisionRecord,
    AgreementEvent,
    AgreementVersion,
    ApprovalTokenRecord,
    ChangeRequest,
)

_ = _engine_transaction


@overload
def _iso(v: datetime) -> str: ...


@overload
def _iso(v: None) -> None: ...


@overload
def _iso(v: datetime | None) -> str | None: ...


def _iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(v: str | None) -> datetime:
    if not v:
        raise ValueError("expected a non-null timestamp")
    return datetime.fromisoformat(v)


def _dt_optional(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v)


class AgreementRepository:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.metadata = MetaData()
        self._define_tables()

    def _define_tables(self) -> None:
        self.agreements = Table(
            "agreements", self.metadata,
            Column("agreement_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, unique=True),
            Column("run_id", String, nullable=False, index=True),
            Column("buyer_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False, index=True),
            Column("buyer_organization_id", String, nullable=True, index=True),
            Column("seller_organization_id", String, nullable=True, index=True),
            Column("current_version", Integer, nullable=False),
            Column("status", String, nullable=False, index=True),
            Column("offer_id", String, nullable=False),
            Column("offer_round", Integer, nullable=False),
            Column("offer_hash", String, nullable=False),
            Column("offer_valid_until", String, nullable=False),
            Column("expires_at", String, nullable=True),
            Column("agreed_at", String, nullable=True),
            Column("rejected_at", String, nullable=True),
            Column("expired_at", String, nullable=True),
            Column("terminated_at", String, nullable=True),
            Column("terminal_reason", String, nullable=True),
            Column("seller_operator_required", Integer, nullable=False, default=0),
            Column("row_version", Integer, nullable=False, default=1),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.agreement_versions = Table(
            "agreement_versions", self.metadata,
            Column("agreement_id", String, nullable=False),
            Column("version", Integer, nullable=False),
            Column("terms", Text, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("rendered_html", Text, nullable=False),
            Column("renderer_version", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("supersedes_version", Integer, nullable=True),
            Column("change_request_id", String, nullable=True),
            Column("superseded_at", String, nullable=True),
        )
        from sqlalchemy import PrimaryKeyConstraint
        self.agreement_versions.append_constraint(
            PrimaryKeyConstraint("agreement_id", "version", name="pk_agreement_versions")
        )
        self.agreement_decisions = Table(
            "agreement_decisions", self.metadata,
            Column("decision_id", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("party", String, nullable=False),
            Column("decision", String, nullable=False),
            Column("actor_type", String, nullable=False),
            Column("actor_id", String, nullable=False),
            Column("authority_ref", String, nullable=True),
            Column("authority_snapshot", Text, nullable=True),
            Column("agreement_hash", String, nullable=False),
            Column("verified_offer_hash", String, nullable=True),
            Column("verified_change_request_id", String, nullable=True),
            Column("reason_code", String, nullable=True),
            Column("note", Text, nullable=False, default=""),
            Column("change_request_id", String, nullable=True),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("decided_at", String, nullable=False),
        )
        self.agreement_change_requests = Table(
            "agreement_change_requests", self.metadata,
            Column("change_request_id", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("base_version", Integer, nullable=False),
            Column("base_hash", String, nullable=False),
            Column("requested_by_party", String, nullable=False),
            Column("requested_by_actor_type", String, nullable=False),
            Column("requested_by_actor_id", String, nullable=False),
            Column("operations", Text, nullable=False),
            Column("reason", Text, nullable=False, default=""),
            Column("status", String, nullable=False, index=True),
            Column("resolved_by_party", String, nullable=True),
            Column("resolved_by_actor_type", String, nullable=True),
            Column("resolved_by_actor_id", String, nullable=True),
            Column("resolution_note", Text, nullable=True),
            Column("resulting_version", Integer, nullable=True),
            Column("created_at", String, nullable=False),
            Column("resolved_at", String, nullable=True),
        )
        self.agreement_approval_tokens = Table(
            "agreement_approval_tokens", self.metadata,
            Column("jti", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("subject_id", String, nullable=False),
            Column("token_hash", String, nullable=False),
            Column("issued_at", String, nullable=False),
            Column("expires_at", String, nullable=False, index=True),
            Column("used_at", String, nullable=True),
            Column("revoked_at", String, nullable=True),
            Column("issued_by_actor_type", String, nullable=False),
            Column("issued_by_actor_id", String, nullable=False),
            Column("consumed_by_decision_id", String, nullable=True),
        )
        self.agreement_events = Table(
            "agreement_events", self.metadata,
            Column("event_id", Integer, primary_key=True, autoincrement=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=True),
            Column("event_type", String, nullable=False),
            Column("payload", Text, nullable=False),
            Column("actor_type", String, nullable=False),
            Column("actor_id", String, nullable=False),
            Column("created_at", String, nullable=False),
        )

    async def create_schema(self, conn: AsyncConnection) -> None:
        await conn.run_sync(self.metadata.create_all)
        await conn.execute(_json_mod.text if False else __import__("sqlalchemy").text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_change_pending "
            "ON agreement_change_requests(agreement_id) WHERE status = 'PENDING'"
        ))

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncConnection, None]:
        async with self.engine.begin() as conn:
            yield conn

    def _row_to_agreement(self, row) -> Agreement:
        return Agreement(
            agreement_id=row["agreement_id"],
            transaction_id=row["transaction_id"],
            run_id=row["run_id"],
            buyer_id=row["buyer_id"],
            seller_id=row["seller_id"],
            current_version=row["current_version"],
            status=AgreementState(row["status"]),
            offer_id=row["offer_id"],
            offer_round=row["offer_round"],
            offer_hash=row["offer_hash"],
            offer_valid_until=_dt(row["offer_valid_until"]),
            expires_at=_dt_optional(row["expires_at"]),
            agreed_at=_dt_optional(row["agreed_at"]),
            rejected_at=_dt_optional(row["rejected_at"]),
            expired_at=_dt_optional(row["expired_at"]),
            terminated_at=_dt_optional(row["terminated_at"]),
            terminal_reason=row["terminal_reason"],
            seller_operator_required=bool(row["seller_operator_required"]),
            row_version=row["row_version"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    async def create(self, conn, agreement: Agreement, version: AgreementVersion) -> None:
        await conn.execute(self.agreements.insert().values(
            agreement_id=agreement.agreement_id,
            transaction_id=agreement.transaction_id,
            run_id=agreement.run_id,
            buyer_id=agreement.buyer_id,
            seller_id=agreement.seller_id,
            current_version=agreement.current_version,
            status=agreement.status.value,
            offer_id=agreement.offer_id,
            offer_round=agreement.offer_round,
            offer_hash=agreement.offer_hash,
            offer_valid_until=_iso(agreement.offer_valid_until),
            expires_at=_iso(agreement.expires_at),
            agreed_at=_iso(agreement.agreed_at),
            rejected_at=_iso(agreement.rejected_at),
            expired_at=_iso(agreement.expired_at),
            terminated_at=_iso(agreement.terminated_at),
            terminal_reason=agreement.terminal_reason,
            seller_operator_required=1 if agreement.seller_operator_required else 0,
            row_version=agreement.row_version,
            created_at=_iso(agreement.created_at),
            updated_at=_iso(agreement.updated_at),
        ))
        await conn.execute(self.agreement_versions.insert().values(
            agreement_id=version.agreement_id,
            version=version.version,
            terms=_json_mod.dumps(version.terms, sort_keys=True),
            agreement_hash=version.agreement_hash,
            rendered_html=version.rendered_html,
            renderer_version=version.renderer_version,
            created_at=_iso(version.created_at),
            supersedes_version=version.supersedes_version,
            change_request_id=version.change_request_id,
            superseded_at=_iso(version.superseded_at),
        ))

    async def get(self, agreement_id: str, conn=None) -> Agreement | None:
        if conn is None:
            async with self.engine.connect() as c:
                return await self._get_with_conn(c, agreement_id)
        return await self._get_with_conn(conn, agreement_id)

    async def _get_with_conn(self, conn, agreement_id: str) -> Agreement | None:
        row = (await conn.execute(
            self.agreements.select().where(self.agreements.c.agreement_id == agreement_id)
        )).mappings().first()
        if row is None:
            return None
        agr = self._row_to_agreement(row)
        ver_row = (await conn.execute(
            self.agreement_versions.select().where(
                self.agreement_versions.c.agreement_id == agreement_id,
                self.agreement_versions.c.version == agr.current_version,
            )
        )).mappings().first()
        if ver_row is not None:
            agr.current_version_record = AgreementVersion(
                agreement_id=ver_row["agreement_id"],
                version=ver_row["version"],
                terms=_json_mod.loads(ver_row["terms"]),
                agreement_hash=ver_row["agreement_hash"],
                rendered_html=ver_row["rendered_html"],
                renderer_version=ver_row["renderer_version"],
                created_at=_dt(ver_row["created_at"]),
                supersedes_version=ver_row["supersedes_version"],
                change_request_id=ver_row["change_request_id"],
                superseded_at=_dt_optional(ver_row["superseded_at"]),
            )
        return agr

    async def get_by_transaction(self, transaction_id: str, conn=None) -> Agreement | None:
        if conn is None:
            async with self.engine.connect() as c:
                row = (await c.execute(
                    self.agreements.select().where(self.agreements.c.transaction_id == transaction_id)
                )).mappings().first()
                if row is None:
                    return None
                return await self.get(row["agreement_id"], conn=c)
        row = (await conn.execute(
            self.agreements.select().where(self.agreements.c.transaction_id == transaction_id)
        )).mappings().first()
        if row is None:
            return None
        return await self.get(row["agreement_id"], conn=conn)

    async def list_all(self, conn=None) -> list[Agreement]:
        if conn is None:
            async with self.engine.connect() as c:
                return await self._list_all_with_conn(c)
        return await self._list_all_with_conn(conn)

    async def _list_all_with_conn(self, conn) -> list[Agreement]:
        rows = (await conn.execute(
            self.agreements.select().order_by(self.agreements.c.created_at.desc())
        )).mappings().all()
        result: list[Agreement] = []
        for row in rows:
            agr = await self.get(row["agreement_id"], conn=conn)
            if agr is not None:
                result.append(agr)
        return result

    async def get_version(self, agreement_id: str, version: int, conn=None) -> AgreementVersion | None:
        if conn is None:
            async with self.engine.connect() as c:
                row = (await c.execute(
                    self.agreement_versions.select().where(
                        self.agreement_versions.c.agreement_id == agreement_id,
                        self.agreement_versions.c.version == version,
                    )
                )).mappings().first()
        else:
            row = (await conn.execute(
                self.agreement_versions.select().where(
                    self.agreement_versions.c.agreement_id == agreement_id,
                    self.agreement_versions.c.version == version,
                )
            )).mappings().first()
        if row is None:
            return None
        return AgreementVersion(
            agreement_id=row["agreement_id"], version=row["version"],
            terms=_json_mod.loads(row["terms"]), agreement_hash=row["agreement_hash"],
            rendered_html=row["rendered_html"], renderer_version=row["renderer_version"],
            created_at=_dt(row["created_at"]), supersedes_version=row["supersedes_version"],
            change_request_id=row["change_request_id"],
            superseded_at=_dt_optional(row["superseded_at"]),
        )

    async def list_versions(self, agreement_id: str, conn=None) -> list[AgreementVersion]:
        if conn is None:
            async with self.engine.connect() as c:
                rows = (await c.execute(
                    self.agreement_versions.select().where(
                        self.agreement_versions.c.agreement_id == agreement_id
                    ).order_by(self.agreement_versions.c.version)
                )).mappings().all()
        else:
            rows = (await conn.execute(
                self.agreement_versions.select().where(
                    self.agreement_versions.c.agreement_id == agreement_id
                ).order_by(self.agreement_versions.c.version)
            )).mappings().all()
        return [AgreementVersion(
            agreement_id=r["agreement_id"], version=r["version"],
            terms=_json_mod.loads(r["terms"]), agreement_hash=r["agreement_hash"],
            rendered_html=r["rendered_html"], renderer_version=r["renderer_version"],
            created_at=_dt(r["created_at"]), supersedes_version=r["supersedes_version"],
            change_request_id=r["change_request_id"],
            superseded_at=_dt_optional(r["superseded_at"]),
        ) for r in rows]

    async def append_decision(self, conn, decision: AgreementDecisionRecord) -> None:
        await conn.execute(self.agreement_decisions.insert().values(
            decision_id=decision.decision_id,
            agreement_id=decision.agreement_id,
            version=decision.version,
            party=decision.party,
            decision=decision.decision.value,
            actor_type=decision.actor_type,
            actor_id=decision.actor_id,
            authority_ref=decision.authority_ref,
            authority_snapshot=_json_mod.dumps(decision.authority_snapshot or {}),
            agreement_hash=decision.agreement_hash,
            verified_offer_hash=decision.verified_offer_hash,
            verified_change_request_id=decision.verified_change_request_id,
            reason_code=decision.reason_code,
            note=decision.note,
            change_request_id=decision.change_request_id,
            idempotency_key=decision.idempotency_key,
            decided_at=_iso(decision.decided_at),
        ))

    async def update_status_cas(self, *args, expected_status, expected_row_version,
                                new_status, new_row_version, expires_at, now,
                                extra: dict[str, Any] | None = None,
                                conn=None) -> bool:
        if len(args) == 2:
            conn = args[0]
            agreement_id = args[1]
        elif len(args) == 1:
            agreement_id = args[0]
        else:
            raise TypeError("update_status_cas requires agreement_id")
        values = {
            "status": new_status.value if hasattr(new_status, "value") else new_status,
            "row_version": new_row_version,
            "updated_at": _iso(now),
            "expires_at": _iso(expires_at),
        }
        if extra:
            values.update(extra)
        stmt = self.agreements.update().where(
            self.agreements.c.agreement_id == agreement_id,
            self.agreements.c.status == (expected_status.value if hasattr(expected_status, "value") else expected_status),
            self.agreements.c.row_version == expected_row_version,
            (self.agreements.c.expires_at.is_(None))
            | (self.agreements.c.expires_at >= _iso(now)),
        )
        if conn is None:
            async with self.engine.begin() as c:
                result = await c.execute(stmt.values(**values))
                return result.rowcount == 1
        result = await conn.execute(stmt.values(**values))
        return result.rowcount == 1

    async def create_change_request(self, conn, cr: ChangeRequest) -> None:
        await conn.execute(self.agreement_change_requests.insert().values(
            change_request_id=cr.change_request_id,
            agreement_id=cr.agreement_id,
            base_version=cr.base_version,
            base_hash=cr.base_hash,
            requested_by_party=cr.requested_by_party,
            requested_by_actor_type=cr.requested_by_actor_type,
            requested_by_actor_id=cr.requested_by_actor_id,
            operations=_json_mod.dumps([o.model_dump(mode="json") for o in cr.operations]),
            reason=cr.reason,
            status=cr.status,
            created_at=_iso(cr.created_at),
        ))

    async def get_open_change_request(self, agreement_id: str, conn=None) -> ChangeRequest | None:
        if conn is None:
            async with self.engine.connect() as c:
                row = (await c.execute(
                    self.agreement_change_requests.select().where(
                        self.agreement_change_requests.c.agreement_id == agreement_id,
                        self.agreement_change_requests.c.status == "PENDING",
                    )
                )).mappings().first()
        else:
            row = (await conn.execute(
                self.agreement_change_requests.select().where(
                    self.agreement_change_requests.c.agreement_id == agreement_id,
                    self.agreement_change_requests.c.status == "PENDING",
                )
            )).mappings().first()
        if row is None:
            return None
        from verifund_contracts.models import ChangeOperation
        ops = [ChangeOperation.model_validate(o) for o in _json_mod.loads(row["operations"])]
        return ChangeRequest(
            change_request_id=row["change_request_id"],
            agreement_id=row["agreement_id"],
            base_version=row["base_version"],
            base_hash=row["base_hash"],
            requested_by_party=row["requested_by_party"],
            requested_by_actor_type=row["requested_by_actor_type"],
            requested_by_actor_id=row["requested_by_actor_id"],
            operations=ops,
            reason=row["reason"],
            status=row["status"],
            resolved_by_party=row["resolved_by_party"],
            resolved_by_actor_type=row["resolved_by_actor_type"],
            resolved_by_actor_id=row["resolved_by_actor_id"],
            resolution_note=row["resolution_note"] or "",
            resulting_version=row["resulting_version"],
            created_at=_dt(row["created_at"]),
            resolved_at=_dt_optional(row["resolved_at"]),
        )

    async def resolve_change_request(self, conn, change_request_id: str, *,
                                    status: str, resolved_by_party: str,
                                    resolved_by_actor_type: str, resolved_by_actor_id: str,
                                    resolution_note: str, resulting_version: int | None,
                                    resolved_at: datetime) -> None:
        await conn.execute(self.agreement_change_requests.update().where(
            self.agreement_change_requests.c.change_request_id == change_request_id,
        ).values(
            status=status,
            resolved_by_party=resolved_by_party,
            resolved_by_actor_type=resolved_by_actor_type,
            resolved_by_actor_id=resolved_by_actor_id,
            resolution_note=resolution_note,
            resulting_version=resulting_version,
            resolved_at=_iso(resolved_at),
        ))

    async def issue_token(self, conn, token: ApprovalTokenRecord) -> None:
        await conn.execute(self.agreement_approval_tokens.insert().values(
            jti=token.jti,
            agreement_id=token.agreement_id,
            version=token.version,
            agreement_hash=token.agreement_hash,
            subject_id=token.subject_id,
            token_hash=token.token_hash,
            issued_at=_iso(token.issued_at),
            expires_at=_iso(token.expires_at),
            used_at=None,
            revoked_at=None,
            issued_by_actor_type=token.issued_by_actor_type,
            issued_by_actor_id=token.issued_by_actor_id,
            consumed_by_decision_id=None,
        ))

    async def consume_token(self, conn, jti: str, now: datetime,
                            consumed_by_decision_id: str) -> bool:
        stmt = self.agreement_approval_tokens.update().where(
            self.agreement_approval_tokens.c.jti == jti,
            self.agreement_approval_tokens.c.used_at.is_(None),
            self.agreement_approval_tokens.c.revoked_at.is_(None),
        ).values(used_at=_iso(now), consumed_by_decision_id=consumed_by_decision_id)
        result = await conn.execute(stmt)
        return result.rowcount == 1

    async def revoke_tokens(self, conn, agreement_id: str, version: int, now: datetime) -> None:
        await conn.execute(self.agreement_approval_tokens.update().where(
            self.agreement_approval_tokens.c.agreement_id == agreement_id,
            self.agreement_approval_tokens.c.version == version,
            self.agreement_approval_tokens.c.used_at.is_(None),
            self.agreement_approval_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=_iso(now)))

    async def get_token(self, jti: str, conn=None) -> ApprovalTokenRecord | None:
        if conn is None:
            async with self.engine.connect() as c:
                row = (await c.execute(
                    self.agreement_approval_tokens.select().where(
                        self.agreement_approval_tokens.c.jti == jti
                    )
                )).mappings().first()
        else:
            row = (await conn.execute(
                self.agreement_approval_tokens.select().where(
                    self.agreement_approval_tokens.c.jti == jti
                )
            )).mappings().first()
        if row is None:
            return None
        return ApprovalTokenRecord(
            jti=row["jti"], agreement_id=row["agreement_id"],
            version=row["version"], agreement_hash=row["agreement_hash"],
            subject_id=row["subject_id"], token_hash=row["token_hash"],
            issued_at=_dt(row["issued_at"]), expires_at=_dt(row["expires_at"]),
            used_at=_dt_optional(row["used_at"]), revoked_at=_dt_optional(row["revoked_at"]),
            issued_by_actor_type=row["issued_by_actor_type"],
            issued_by_actor_id=row["issued_by_actor_id"],
            consumed_by_decision_id=row["consumed_by_decision_id"],
        )

    async def append_event(self, conn, event: AgreementEvent) -> None:
        await conn.execute(self.agreement_events.insert().values(
            agreement_id=event.agreement_id,
            version=event.version,
            event_type=event.event_type,
            payload=_json_mod.dumps(event.payload, sort_keys=True),
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            created_at=_iso(event.created_at),
        ))

    async def list_events(self, agreement_id: str, conn=None) -> list[AgreementEvent]:
        if conn is None:
            async with self.engine.connect() as c:
                rows = (await c.execute(
                    self.agreement_events.select().where(
                        self.agreement_events.c.agreement_id == agreement_id
                    ).order_by(self.agreement_events.c.event_id)
                )).mappings().all()
        else:
            rows = (await conn.execute(
                self.agreement_events.select().where(
                    self.agreement_events.c.agreement_id == agreement_id
                ).order_by(self.agreement_events.c.event_id)
            )).mappings().all()
        return [AgreementEvent(
            event_id=r["event_id"], agreement_id=r["agreement_id"],
            version=r["version"], event_type=r["event_type"],
            payload=_json_mod.loads(r["payload"]), actor_type=r["actor_type"],
            actor_id=r["actor_id"], created_at=_dt(r["created_at"]),
        ) for r in rows]

    async def list_expired(self, now: datetime, limit: int = 100, conn=None) -> list[str]:
        if conn is None:
            async with self.engine.connect() as c:
                rows = (await c.execute(
                    self.agreements.select().where(
                        self.agreements.c.status.in_(["PENDING_SELLER", "PENDING_BUYER", "CHANGES_REQUESTED"]),
                        self.agreements.c.expires_at.is_not(None),
                        self.agreements.c.expires_at <= _iso(now),
                    ).limit(limit)
                )).mappings().all()
        else:
            rows = (await conn.execute(
                self.agreements.select().where(
                    self.agreements.c.status.in_(["PENDING_SELLER", "PENDING_BUYER", "CHANGES_REQUESTED"]),
                    self.agreements.c.expires_at.is_not(None),
                    self.agreements.c.expires_at <= _iso(now),
                ).limit(limit)
            )).mappings().all()
        return [r["agreement_id"] for r in rows]

    async def expire(self, conn, agreement_id: str, expected_row_version: int, now: datetime) -> bool:
        stmt = self.agreements.update().where(
            self.agreements.c.agreement_id == agreement_id,
            self.agreements.c.row_version == expected_row_version,
            self.agreements.c.expires_at.is_not(None),
            self.agreements.c.expires_at <= _iso(now),
        ).values(
            status="EXPIRED", expired_at=_iso(now), row_version=expected_row_version + 1,
            updated_at=_iso(now),
        )
        result = await conn.execute(stmt)
        return result.rowcount == 1

    async def create_version(self, conn, version: AgreementVersion) -> None:
        await conn.execute(self.agreement_versions.insert().values(
            agreement_id=version.agreement_id,
            version=version.version,
            terms=_json_mod.dumps(version.terms, sort_keys=True),
            agreement_hash=version.agreement_hash,
            rendered_html=version.rendered_html,
            renderer_version=version.renderer_version,
            created_at=_iso(version.created_at),
            supersedes_version=version.supersedes_version,
            change_request_id=version.change_request_id,
            superseded_at=_iso(version.superseded_at),
        ))

    @staticmethod
    def _row_to_decision(r) -> AgreementDecisionRecord:
        return AgreementDecisionRecord(
            decision_id=r["decision_id"], agreement_id=r["agreement_id"],
            version=r["version"], party=r["party"],
            decision=AgreementDecision(r["decision"]),
            actor_type=r["actor_type"], actor_id=r["actor_id"],
            authority_ref=r["authority_ref"],
            authority_snapshot=_json_mod.loads(r["authority_snapshot"] or "{}"),
            agreement_hash=r["agreement_hash"],
            verified_offer_hash=r["verified_offer_hash"],
            verified_change_request_id=r["verified_change_request_id"],
            reason_code=r["reason_code"], note=r["note"],
            change_request_id=r["change_request_id"],
            idempotency_key=r["idempotency_key"], decided_at=_dt(r["decided_at"]),
        )

    async def list_decisions(self, agreement_id: str, conn=None) -> list[AgreementDecisionRecord]:
        if conn is None:
            async with self.engine.connect() as c:
                rows = (await c.execute(
                    self.agreement_decisions.select().where(
                        self.agreement_decisions.c.agreement_id == agreement_id
                    ).order_by(self.agreement_decisions.c.decided_at)
                )).mappings().all()
                return [self._row_to_decision(r) for r in rows]
        rows = (await conn.execute(
            self.agreement_decisions.select().where(
                self.agreement_decisions.c.agreement_id == agreement_id
            ).order_by(self.agreement_decisions.c.decided_at)
        )).mappings().all()
        return [self._row_to_decision(r) for r in rows]

    async def get_decision_by_idempotency(
        self, key: str, conn=None
    ) -> AgreementDecisionRecord | None:
        decisions = await self.list_decisions_by_key(key, conn=conn)
        return decisions[0] if decisions else None

    async def list_decisions_by_key(
        self, key: str, conn=None
    ) -> list[AgreementDecisionRecord]:
        if conn is None:
            async with self.engine.connect() as c:
                rows = (await c.execute(
                    self.agreement_decisions.select().where(
                        self.agreement_decisions.c.idempotency_key == key
                    ).order_by(self.agreement_decisions.c.decided_at)
                )).mappings().all()
                return [self._row_to_decision(r) for r in rows]
        rows = (await conn.execute(
            self.agreement_decisions.select().where(
                self.agreement_decisions.c.idempotency_key == key
            ).order_by(self.agreement_decisions.c.decided_at)
        )).mappings().all()
        return [self._row_to_decision(r) for r in rows]

    async def set_operator_required(
        self, conn, agreement_id: str, expected_row_version: int, now: datetime
    ) -> bool:
        stmt = self.agreements.update().where(
            self.agreements.c.agreement_id == agreement_id,
            self.agreements.c.row_version == expected_row_version,
            self.agreements.c.status == "PENDING_SELLER",
        ).values(
            seller_operator_required=1,
            row_version=expected_row_version + 1,
            updated_at=_iso(now),
        )
        result = await conn.execute(stmt)
        return result.rowcount == 1
