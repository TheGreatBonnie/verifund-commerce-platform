from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from verifund_control_plane.errors import VerifundError


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        connect_args={"timeout": 5.0},
        pool_pre_ping=True,
    )


async def configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA busy_timeout=5000")


@asynccontextmanager
async def transaction(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    try:
        async with engine.begin() as conn:
            yield conn
    except OperationalError as exc:
        message = str(exc).lower()
        if "database is locked" in message or "database table is locked" in message:
            raise VerifundError(
                "internal",
                "SQLite is busy; retry shortly",
                status_code=503,
                retryable=True,
            ) from exc
        raise
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise VerifundError(
                "internal",
                "SQLite is busy; retry shortly",
                status_code=503,
                retryable=True,
            ) from exc
        raise
