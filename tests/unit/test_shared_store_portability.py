"""The product upsert must run on PostgreSQL as well as SQLite.

SQLite has a ``datetime('now')`` function; PostgreSQL does not, so the
expression has to be a bound value instead of an inline function call.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql, sqlite

from seller_agent.shared_store import product_upsert_statement

COLS = {
    "organization_id": "org-1",
    "sku": "EX-4K-GAMING-MONITOR",
    "name": "4K Gaming Monitor",
    "updated_at": "2026-11-12T22:37:09.123456+00:00",
}


def test_product_upsert_does_not_use_sqlite_datetime() -> None:
    statement = product_upsert_statement(COLS)

    assert "datetime(" not in statement.text


def test_product_upsert_binds_the_update_timestamp() -> None:
    statement = product_upsert_statement(COLS)

    assert ":updated_at" in statement.text


def test_product_upsert_compiles_for_postgresql() -> None:
    compiled = str(
        product_upsert_statement(COLS).compile(dialect=postgresql.dialect())
    )

    assert "%(" in compiled
    assert "datetime(" not in compiled


def test_product_upsert_compiles_for_sqlite() -> None:
    compiled = str(product_upsert_statement(COLS).compile(dialect=sqlite.dialect()))

    assert "?" in compiled
    assert "datetime(" not in compiled
