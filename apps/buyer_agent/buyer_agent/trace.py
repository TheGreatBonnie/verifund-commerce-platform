from __future__ import annotations

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
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

SENSITIVE_KEYS = {"authorization", "cookie", "x-api-key", "token"}
MAX_PAYLOAD_BYTES = 256 * 1024


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
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

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
            event_id = result.inserted_primary_key[0]
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

    async def list(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[TraceEvent]:
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
        now = datetime.now(UTC).isoformat()
        values: dict[str, Any] = {
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "stage": fields.get("stage", "new"),
            "mandate_json": fields.get("mandate_json", fields.get("mandate")),
            "award_json": fields.get("award_json", fields.get("award")),
            "order_json": fields.get("order_json", fields.get("order")),
            "error": fields.get("error"),
        }
        statement = sqlite_insert(self.runs).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["run_id"],
            set_={
                key: value
                for key, value in values.items()
                if key not in {"run_id", "created_at"}
            },
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

    async def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.runs)
                .order_by(self.runs.c.updated_at.desc())
                .limit(limit)
            )
            return [dict(row._mapping) for row in result]
