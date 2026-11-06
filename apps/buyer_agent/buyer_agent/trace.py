from __future__ import annotations

import builtins
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from a2a.types.a2a_pb2 import StreamResponse
from commerce_core.db import configure_sqlite
from google.protobuf import json_format
from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

SENSITIVE_KEYS = {"authorization", "cookie", "x-api-key", "token"}
MAX_PAYLOAD_BYTES = 256 * 1024


async def _reflected_column_names(
    conn: Any, table: str
) -> set[str]:
    def _reflect(sync_conn: Any) -> set[str]:
        inspector = sa_inspect(sync_conn)
        return {c["name"] for c in inspector.get_columns(table)}

    return set(await conn.run_sync(_reflect))


def redact(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in SENSITIVE_KEYS
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def truncate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = redact(payload)
    encoded = json.dumps(redacted, default=str).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        return {"truncated": True, "bytes": len(encoded)}
    return redacted


@dataclass
class TraceEvent:
    id: int
    run_id: str
    seq: int
    created_at: str
    direction: str
    seller_id: str | None
    method: str
    task_id: str | None
    context_id: str | None
    payload: dict[str, Any]
    latency_ms: int | None


class TraceStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self.events = Table(
            "trace_events",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("run_id", String, nullable=False),
            Column("seq", Integer, nullable=False),
            Column("created_at", String, nullable=False),
            Column("direction", String, nullable=False),
            Column("seller_id", String, nullable=True),
            Column("method", String, nullable=False),
            Column("task_id", String, nullable=True),
            Column("context_id", String, nullable=True),
            Column("payload_json", JSON, nullable=False),
            Column("latency_ms", Integer, nullable=True),
        )
        self.runs = Table(
            "runs",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
            Column("stage", String, nullable=False, default="new"),
            Column("mandate_json", JSON, nullable=True),
            Column("award_json", JSON, nullable=True),
            Column("order_json", JSON, nullable=True),
            Column("error", String, nullable=True),
            Column("organization_id", String, nullable=True, index=True),
            Column("user_id", String, nullable=True),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)
            for column in ("organization_id", "user_id"):
                cols = await _reflected_column_names(conn, "runs")
                if column not in cols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE runs ADD COLUMN {column} TEXT"
                    )

    async def record(
        self,
        run_id: str,
        *,
        direction: str,
        method: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        context_id: str | None = None,
        seller_id: str | None = None,
        latency_ms: int | None = None,
    ) -> TraceEvent:
        now = datetime.now(UTC).isoformat()
        clean = truncate_payload(payload)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                select(self.events.c.seq)
                .where(self.events.c.run_id == run_id)
                .order_by(self.events.c.seq.desc())
                .limit(1)
            )
            row = result.first()
            seq = (row.seq if row else 0) + 1
            result = await conn.execute(
                self.events.insert().values(
                    run_id=run_id,
                    seq=seq,
                    created_at=now,
                    direction=direction,
                    seller_id=seller_id,
                    method=method,
                    task_id=task_id,
                    context_id=context_id,
                    payload_json=clean,
                    latency_ms=latency_ms,
                )
            )
            inserted = result.inserted_primary_key
            if inserted is None:
                raise RuntimeError("Insert did not return a primary key")
            event_id = int(inserted[0])
        return TraceEvent(
            id=event_id,
            run_id=run_id,
            seq=seq,
            created_at=now,
            direction=direction,
            seller_id=seller_id,
            method=method,
            task_id=task_id,
            context_id=context_id,
            payload=clean,
            latency_ms=latency_ms,
        )

    # `builtins.list` keeps the annotation from resolving to this method name.
    async def list(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> builtins.list[TraceEvent]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.events)
                .where(self.events.c.run_id == run_id)
                .where(self.events.c.seq > after_seq)
                .order_by(self.events.c.seq)
                .limit(limit)
            )
            return [
                TraceEvent(
                    id=row.id,
                    run_id=row.run_id,
                    seq=row.seq,
                    created_at=row.created_at,
                    direction=row.direction,
                    seller_id=row.seller_id,
                    method=row.method,
                    task_id=row.task_id,
                    context_id=row.context_id,
                    payload=row.payload_json,
                    latency_ms=row.latency_ms,
                )
                for row in result
            ]

    async def record_message(
        self,
        run_id: str,
        seller_id: str,
        message,
        *,
        method: str = "SendStreamingMessage",
    ) -> None:
        payload: dict[str, Any] = {
            "kind": "message",
            "message": json_format.MessageToDict(message),
        }
        await self.record(
            run_id,
            direction="outbound",
            method=method,
            payload=payload,
            task_id=message.task_id or None,
            context_id=message.context_id or None,
            seller_id=seller_id,
        )

    async def record_frame(
        self,
        run_id: str,
        seller_id: str,
        frame: StreamResponse,
        *,
        latency_ms: int | None = None,
    ) -> None:
        kind = frame.WhichOneof("payload") or "unknown"
        payload: dict[str, Any] = {"kind": kind}
        task_id = None
        context_id = None
        if kind == "task":
            payload["task"] = json_format.MessageToDict(frame.task)
            task_id = frame.task.id
            context_id = frame.task.context_id
        elif kind == "status_update":
            payload["statusUpdate"] = json_format.MessageToDict(
                frame.status_update
            )
            task_id = frame.status_update.task_id
            context_id = frame.status_update.context_id
        elif kind == "artifact_update":
            payload["artifactUpdate"] = json_format.MessageToDict(
                frame.artifact_update
            )
            task_id = frame.artifact_update.task_id
            context_id = frame.artifact_update.context_id
        elif kind == "message":
            payload["message"] = json_format.MessageToDict(frame.message)
            task_id = frame.message.task_id or None
            context_id = frame.message.context_id or None
        await self.record(
            run_id,
            direction="inbound",
            method="SendStreamingMessage",
            payload=payload,
            task_id=task_id,
            context_id=context_id,
            seller_id=seller_id,
            latency_ms=latency_ms,
        )

    async def upsert_run(self, run_id: str, **fields: Any) -> None:
        _UNSET = object()
        now = datetime.now(UTC).isoformat()
        # Resolve optional fields; _UNSET means "not provided by caller".
        stage = fields.get("stage", _UNSET)
        mandate = fields.get("mandate_json", fields.get("mandate", _UNSET))
        award = fields.get("award_json", fields.get("award", _UNSET))
        order = fields.get("order_json", fields.get("order", _UNSET))
        error = fields.get("error", _UNSET)
        organization_id = fields.get("organization_id", _UNSET)
        user_id = fields.get("user_id", _UNSET)

        insert_values: dict[str, Any] = {
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "stage": stage if stage is not _UNSET else "new",
            "mandate_json": mandate if mandate is not _UNSET else None,
            "award_json": award if award is not _UNSET else None,
            "order_json": order if order is not _UNSET else None,
            "error": error if error is not _UNSET else None,
            "organization_id": organization_id
            if organization_id is not _UNSET
            else None,
            "user_id": user_id if user_id is not _UNSET else None,
        }
        statement = sqlite_insert(self.runs).values(**insert_values)
        # On conflict, only overwrite fields the caller actually provided so
        # that a later stage transition (e.g. "awarded") does not erase an
        # award/order/mandate persisted by an earlier one.
        update_set: dict[str, Any] = {"updated_at": now}
        if stage is not _UNSET:
            update_set["stage"] = stage
        if mandate is not _UNSET:
            update_set["mandate_json"] = mandate
        if award is not _UNSET:
            update_set["award_json"] = award
        if order is not _UNSET:
            update_set["order_json"] = order
        if error is not _UNSET:
            update_set["error"] = error
        if organization_id is not _UNSET:
            update_set["organization_id"] = organization_id
        if user_id is not _UNSET:
            update_set["user_id"] = user_id
        statement = statement.on_conflict_do_update(
            index_elements=["run_id"],
            set_=update_set,
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.runs).where(self.runs.c.run_id == run_id)
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def list_runs(
        self, organization_id: str | None = None, *, limit: int = 50
    ) -> builtins.list[dict[str, Any]]:
        statement = select(self.runs).order_by(self.runs.c.updated_at.desc())
        if organization_id is not None:
            statement = statement.where(
                self.runs.c.organization_id == organization_id
            )
        async with self.engine.connect() as conn:
            result = await conn.execute(statement.limit(limit))
            return [dict(row._mapping) for row in result]
