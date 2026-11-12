import pytest
from commerce_core.db import (
    configure_database,
    dialect_insert,
    existing_columns,
    is_postgres_url,
    libpq_dsn,
    portable_ddl,
    row_was_written,
)
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+psycopg://user:pw@host:5432/db", True),
        ("postgresql://user:pw@host:5432/db", True),
        ("postgres://user:pw@host/db", True),
        ("sqlite+aiosqlite:////app/data/buyer.db", False),
        ("sqlite:///./data/buyer.db", False),
        ("", False),
    ],
)
def test_is_postgres_url(url: str, expected: bool) -> None:
    assert is_postgres_url(url) is expected


@pytest.mark.parametrize("dialect_name", ["postgresql", "sqlite"])
def test_dialect_insert_builds_upsert_for_target_dialect(dialect_name: str) -> None:
    metadata = MetaData()
    sellers = Table(
        "sellers",
        metadata,
        Column("seller_id", String(64), primary_key=True),
        Column("name", String, nullable=False),
    )
    statement = dialect_insert(sellers, dialect_name).values(
        seller_id="northwind-audio", name="Northwind"
    ).on_conflict_do_update(
        index_elements=["seller_id"], set_={"name": "Northwind"}
    )
    dialect = postgresql.dialect() if dialect_name == "postgresql" else sqlite.dialect()
    compiled = str(statement.compile(dialect=dialect))
    assert "ON CONFLICT" in compiled.upper()
    assert "DO UPDATE SET" in compiled.upper()


class _FakeResult:
    def __init__(self, rowcount, row=None) -> None:
        self.rowcount = rowcount
        self._row = row

    def first(self):
        return self._row


class _FakeCursor:
    """Minimal AsyncConnection stand-in for sqlite_file_path-free checks."""


def test_row_was_written_uses_rowcount_when_reported() -> None:
    assert row_was_written(_FakeResult(1)) is True
    assert row_was_written(_FakeResult(0)) is False


def test_row_was_written_falls_back_to_returning_when_rowcount_unknown() -> None:
    # psycopg reports -1 for INSERTs; the RETURNING row decides instead.
    assert row_was_written(_FakeResult(-1, row=("id",))) is True
    assert row_was_written(_FakeResult(-1, row=None)) is False


def test_portable_ddl_rewrites_sqlite_defaults_for_postgres() -> None:
    ddl = (
        "CREATE TABLE IF NOT EXISTS evidence_outbox ("
        "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "content BLOB NOT NULL DEFAULT X''"
        ")"
    )
    rewritten = portable_ddl(ddl, "postgresql")
    assert "datetime('now')" not in rewritten
    assert "now()" in rewritten
    assert "BLOB" not in rewritten
    assert "BYTEA" in rewritten
    assert "X''" not in rewritten


def test_libpq_dsn_strips_sqlalchemy_driver() -> None:
    assert (
        libpq_dsn("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    )


def test_portable_ddl_leaves_sqlite_untouched() -> None:
    ddl = "CREATE TABLE t (created_at TEXT NOT NULL DEFAULT (datetime('now')), c BLOB)"
    assert portable_ddl(ddl, "sqlite") == ddl


async def test_configure_database_applies_wal_on_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await configure_database(engine)
        async with engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        assert str(mode).lower() == "memory"
    finally:
        await engine.dispose()


async def test_existing_columns_reads_sqlite_schema() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE sellers (seller_id TEXT, name TEXT)"))
            columns = await existing_columns(conn, "sellers")
        assert columns == {"seller_id", "name"}
    finally:
        await engine.dispose()


async def test_existing_columns_returns_empty_for_missing_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            columns = await existing_columns(conn, "does_not_exist")
        assert columns == set()
    finally:
        await engine.dispose()
