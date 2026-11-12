"""Cross-dialect database helpers shared by every service.

The deployed topology uses PostgreSQL, while local development and the unit
suite keep SQLite. Everything dialect-specific lives here so call sites never
import ``sqlalchemy.dialects.sqlite`` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Table, event, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

_POSTGRES_PREFIXES = ("postgresql", "postgres")


def is_postgres_url(url: str) -> bool:
    """True when ``url`` points at PostgreSQL.

    Accepted forms include ``postgresql+psycopg://``, ``postgresql://`` and
    ``postgres://`` (the scheme Render exposes).
    """

    scheme = url.split("://", 1)[0].strip().lower()
    if not scheme:
        return False
    return scheme.split("+", 1)[0] in _POSTGRES_PREFIXES


def sqlite_file_path(url: str) -> Path | None:
    """Return the on-disk path for a SQLite URL, or ``None`` for PostgreSQL."""

    if is_postgres_url(url):
        return None
    return Path(url.split("///", 1)[-1])


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


async def configure_database(engine: AsyncEngine) -> None:
    """Apply per-dialect connection settings.

    SQLite gets WAL, foreign keys and a busy timeout. PostgreSQL needs none of
    those, so it only pins the session time zone the code already assumes.
    """

    if engine.dialect.name == "postgresql":
        async with engine.begin() as conn:
            await conn.execute(text("SET TIME ZONE 'UTC'"))
        return
    await configure_sqlite(engine)


async def existing_columns(conn: AsyncConnection, table: str) -> set[str]:
    """Return the column names of ``table`` for the connection's dialect."""

    if conn.dialect.name == "postgresql":
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND table_schema = current_schema()"
            ),
            {"table": table},
        )
        return {str(row[0]) for row in result}
    rows = await conn.exec_driver_sql(f'PRAGMA table_info("{table}")')
    return {str(row[1]) for row in rows}


def libpq_dsn(url: str) -> str:
    """Strip the SQLAlchemy driver suffix so ``psycopg`` can parse the URL."""

    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def row_was_written(result: Any) -> bool:
    """Report whether an INSERT actually wrote a row, on either dialect.

    ``psycopg`` reports ``rowcount == -1`` for INSERTs, so statements that
    need this answer must add ``RETURNING``; SQLite reports a real count.
    """

    rowcount = getattr(result, "rowcount", None)
    if rowcount is not None and rowcount >= 0:
        return rowcount > 0
    return result.first() is not None


def dialect_insert(table: Table, dialect_name: str) -> Any:
    """Return the dialect's ``insert`` construct for ``table``.

    Both PostgreSQL and SQLite expose ``on_conflict_do_update`` /
    ``on_conflict_do_nothing``, so call sites keep their existing chains.
    """

    insert = pg_insert if dialect_name == "postgresql" else sqlite_insert
    return insert(table)


def portable_ddl(ddl: str, dialect_name: str) -> str:
    """Rewrite SQLite-flavoured DDL for PostgreSQL.

    Only the constructs this repository's seller schema uses are translated;
    anything else passes through unchanged so SQLite behaviour stays identical.
    """

    if dialect_name != "postgresql":
        return ddl
    rewritten = ddl.replace("datetime('now')", "now()")
    rewritten = rewritten.replace("BLOB", "BYTEA")
    rewritten = rewritten.replace("X''", "''::bytea")
    return rewritten
