from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import psycopg
from commerce_core.db import is_postgres_url, libpq_dsn
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncEngine

TABLE = "seller_agreement_reviews"
COLUMNS = (
    "agreement_id",
    "version",
    "agreement_hash",
    "offer_hash",
    "terms",
    "change_request_id",
    "decision",
    "reviewed_at",
    "task_id",
    "context_id",
)
PRIMARY_KEY = ("agreement_id", "version")


class AgreementReviewStore(Protocol):
    """Duck-typed review store used by agreement review.

    Both `SellerAgreementReviewStore` (single-tenant) and
    `OrgScopedAgreementReviewStore` (shared engine + org scope) satisfy
    this protocol. `review_agreement` only needs these three methods.
    """

    def record(
        self, projection, offer_hash, *, decision, now, task_id, context_id
    ) -> None: ...

    def get(self, agreement_id, version): ...

    def list(self, agreement_id): ...


def _postgres_dsn(engine: AsyncEngine) -> str:
    url = engine.url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


class SellerAgreementReviewStore:
    def __init__(
        self,
        db_path: Path | str,
        *,
        engine: AsyncEngine | None = None,
    ) -> None:
        self.db_path: Path | None = None
        self.dsn: str | None = None
        if engine is not None and engine.url.get_backend_name() == "postgresql":
            self.dsn = _postgres_dsn(engine)
        elif is_postgres_url(str(db_path)):
            self.dsn = libpq_dsn(str(db_path))
        else:
            self.db_path = Path(db_path)
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @property
    def is_postgres(self) -> bool:
        return self.dsn is not None

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        if self.dsn is not None:
            with (
                psycopg.connect(self.dsn, row_factory=dict_row) as conn,
                conn.cursor() as cursor,
            ):
                yield cursor
            return
        assert self.db_path is not None
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                agreement_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                agreement_hash TEXT NOT NULL,
                offer_hash TEXT NOT NULL,
                terms TEXT NOT NULL,
                change_request_id TEXT,
                decision TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                task_id TEXT NOT NULL,
                context_id TEXT NOT NULL,
                PRIMARY KEY (agreement_id, version)
            )"""
            )
        # Guarantee the ON CONFLICT target exists even when the table was
        # created by the org-scoped schema instead.
        with self._cursor() as cursor:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_seller_agreement_reviews_tenant "
                f"ON {TABLE} (agreement_id, version)"
            )

    def _insert_sql(self) -> str:
        column_list = ", ".join(COLUMNS)
        if self.is_postgres:
            placeholders = ", ".join("%s" for _ in COLUMNS)
            updates = ", ".join(
                f"{column} = EXCLUDED.{column}"
                for column in COLUMNS
                if column not in PRIMARY_KEY
            )
            return (
                f"INSERT INTO {TABLE} ({column_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({', '.join(PRIMARY_KEY)}) DO UPDATE SET {updates}"
            )
        placeholders = ", ".join("?" for _ in COLUMNS)
        return (
            f"INSERT OR REPLACE INTO {TABLE} ({column_list}) "
            f"VALUES ({placeholders})"
        )

    def record(self, projection, offer_hash, *, decision, now, task_id, context_id):
        reviewed_at = (
            now.isoformat().replace("+00:00", "Z")
            if hasattr(now, "isoformat")
            else str(now)
        )
        with self._cursor() as cursor:
            cursor.execute(
                self._insert_sql(),
                (
                    projection.agreement_id,
                    projection.agreement_version,
                    projection.agreement_hash,
                    offer_hash,
                    json.dumps(projection.terms, sort_keys=True),
                    projection.change_request_id,
                    decision,
                    reviewed_at,
                    task_id,
                    context_id,
                ),
            )

    def get(self, agreement_id, version):
        marker = "%s" if self.is_postgres else "?"
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {TABLE} WHERE agreement_id={marker} "
                f"AND version={marker}",
                (agreement_id, version),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def list(self, agreement_id):
        marker = "%s" if self.is_postgres else "?"
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {TABLE} WHERE agreement_id={marker} ORDER BY version",
                (agreement_id,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
