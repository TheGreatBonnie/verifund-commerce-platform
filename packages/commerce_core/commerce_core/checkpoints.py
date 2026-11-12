"""Checkpointer selection shared by the buyer, seller and Verifund agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from commerce_core.db import is_postgres_url


def prepare_checkpoint_storage(source: str) -> None:
    """Create the parent directory for a SQLite checkpoint file.

    PostgreSQL needs no filesystem preparation.
    """

    if is_postgres_url(source):
        return
    Path(source).expanduser().parent.mkdir(parents=True, exist_ok=True)


def checkpoint_dsn(source: str) -> str:
    """Normalize a PostgreSQL checkpoint URL into a libpq DSN.

    ``psycopg`` rejects the ``postgresql+psycopg://`` SQLAlchemy driver suffix,
    so the driver is stripped before the string reaches the saver.
    """

    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        raise ValueError(f"not a PostgreSQL URL: {source}")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def open_checkpointer(source: str) -> AsyncIterator[Any]:
    """Open the LangGraph checkpointer for a URL or a SQLite file path.

    PostgreSQL is selected by URL scheme; anything else is treated as a SQLite
    file path so local development keeps working unchanged.
    """

    if is_postgres_url(source):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(
            checkpoint_dsn(source)
        ) as saver:
            await saver.setup()
            yield saver
        return

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(source) as saver:
        yield saver
