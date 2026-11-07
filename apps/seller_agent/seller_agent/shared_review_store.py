from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine


def _db_path(db_path: Path | str | AsyncEngine) -> Path:
    if isinstance(db_path, AsyncEngine):
        database = db_path.url.database
        if not database:
            raise ValueError("shared review store requires a file-backed engine")
        return Path(database)
    return Path(db_path)


class OrgScopedAgreementReviewStore:
    def __init__(self, db_path: Path | str | AsyncEngine,
                 organization_id: str) -> None:
        self.db_path = _db_path(db_path)
        self.organization_id = (organization_id or "").strip()
        if not self.organization_id:
            raise ValueError("organization_id is required")
        self._ensure_schema()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS seller_agreement_reviews (
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
            )""")
            columns = {
                row[1] for row in c.execute(
                    "PRAGMA table_info(seller_agreement_reviews)")
            }
            if "organization_id" not in columns:
                c.execute(
                    "ALTER TABLE seller_agreement_reviews "
                    "ADD COLUMN organization_id TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _iso(now) -> str:
        if hasattr(now, "isoformat"):
            return now.isoformat().replace("+00:00", "Z")
        return str(now)

    def record(self, projection, offer_hash, *, decision, now, task_id,
               context_id) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO seller_agreement_reviews
                   (organization_id, agreement_id, version, agreement_hash,
                    offer_hash, terms, change_request_id, decision, reviewed_at,
                    task_id, context_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (self.organization_id, projection.agreement_id,
                 projection.agreement_version, projection.agreement_hash,
                 offer_hash, json.dumps(projection.terms, sort_keys=True),
                 projection.change_request_id, decision, self._iso(now),
                 task_id, context_id),
            )

    def get(self, agreement_id, version):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM seller_agreement_reviews "
                "WHERE organization_id=? AND agreement_id=? AND version=?",
                (self.organization_id, agreement_id, version),
            ).fetchone()
        return dict(row) if row else None

    def list(self, agreement_id):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM seller_agreement_reviews "
                "WHERE organization_id=? AND agreement_id=? ORDER BY version",
                (self.organization_id, agreement_id),
            ).fetchall()
        return [dict(row) for row in rows]
