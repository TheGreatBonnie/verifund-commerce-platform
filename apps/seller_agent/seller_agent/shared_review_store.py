from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from commerce_core.db import is_postgres_url, libpq_dsn
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncEngine

TABLE = "seller_agreement_reviews"
COLUMNS = (
    "organization_id",
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
PRIMARY_KEY = ("organization_id", "agreement_id", "version")


def _postgres_dsn(engine: AsyncEngine) -> str:
    url = engine.url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


class OrgScopedAgreementReviewStore:
    """Synchronous review projection store scoped to one organization.

    Kept synchronous because agreement review runs inline in the A2A handler.
    The backend is chosen from the engine URL: SQLite for local development and
    PostgreSQL for the deployed topology.
    """

    def __init__(
        self, db_path: Path | str | AsyncEngine, organization_id: str
    ) -> None:
        self.organization_id = (organization_id or "").strip()
        if not self.organization_id:
            raise ValueError("organization_id is required")

        self.db_path: Path | None = None
        self.dsn: str | None = None
        if isinstance(db_path, AsyncEngine):
            if db_path.url.get_backend_name() == "postgresql":
                self.dsn = _postgres_dsn(db_path)
            else:
                database = db_path.url.database
                if not database:
                    raise ValueError(
                        "shared review store requires a file-backed or PostgreSQL engine"
                    )
                self.db_path = Path(database)
        elif is_postgres_url(str(db_path)):
            self.dsn = libpq_dsn(str(db_path))
        else:
            self.db_path = Path(db_path)

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

    def _existing_columns(self) -> set[str]:
        with self._cursor() as cursor:
            if self.is_postgres:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s AND table_schema = current_schema()",
                    (TABLE,),
                )
                return {str(row["column_name"]) for row in cursor.fetchall()}
            cursor.execute(f"PRAGMA table_info({TABLE})")
            return {str(row[1]) for row in cursor.fetchall()}

    def _ensure_schema(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                organization_id TEXT NOT NULL,
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
                PRIMARY KEY (organization_id, agreement_id, version)
            )"""
            )
        if "organization_id" not in self._existing_columns():
            with self._cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE {TABLE} "
                    "ADD COLUMN organization_id TEXT NOT NULL DEFAULT ''"
                )
        # The table may already exist from the single-tenant schema, whose
        # primary key is (agreement_id, version). PostgreSQL's ON CONFLICT
        # needs a unique index matching the org-scoped target exactly.
        with self._cursor() as cursor:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_seller_agreement_reviews_org "
                f"ON {TABLE} (organization_id, agreement_id, version)"
            )

    @staticmethod
    def _iso(now) -> str:
        if hasattr(now, "isoformat"):
            return now.isoformat().replace("+00:00", "Z")
        return str(now)

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

    def _placeholder(self) -> str:
        return "%s" if self.is_postgres else "?"

    def record(
        self, projection, offer_hash, *, decision, now, task_id, context_id
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                self._insert_sql(),
                (
                    self.organization_id,
                    projection.agreement_id,
                    projection.agreement_version,
                    projection.agreement_hash,
                    offer_hash,
                    json.dumps(projection.terms, sort_keys=True),
                    projection.change_request_id,
                    decision,
                    self._iso(now),
                    task_id,
                    context_id,
                ),
            )

    def get(self, agreement_id, version):
        marker = self._placeholder()
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {TABLE} "
                f"WHERE organization_id={marker} AND agreement_id={marker} "
                f"AND version={marker}",
                (self.organization_id, agreement_id, version),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def list(self, agreement_id):
        marker = self._placeholder()
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {TABLE} "
                f"WHERE organization_id={marker} AND agreement_id={marker} "
                "ORDER BY version",
                (self.organization_id, agreement_id),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
