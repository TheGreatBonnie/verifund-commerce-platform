from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from commerce_core.db import configure_database, is_postgres_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from verifund_control_plane.errors import VerifundError

__all__ = ["configure_database", "create_engine", "transaction"]


def create_engine(database_url: str) -> AsyncEngine:
    if is_postgres_url(database_url):
        return create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
        )
    # SQLite keeps its connect timeout; psycopg does not accept it.
    return create_async_engine(
        database_url,
        connect_args={"timeout": 5.0},
        pool_pre_ping=True,
    )


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
