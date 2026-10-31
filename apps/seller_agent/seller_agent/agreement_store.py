from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class SellerAgreementReviewStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _ensure_schema(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS seller_agreement_reviews (
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
            )""")

    def record(self, projection, offer_hash, *, decision, now, task_id, context_id):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO seller_agreement_reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
                (projection.agreement_id, projection.agreement_version,
                 projection.agreement_hash, offer_hash,
                 json.dumps(projection.terms, sort_keys=True),
                 projection.change_request_id, decision,
                 now.isoformat().replace("+00:00", "Z") if hasattr(now, "isoformat") else str(now),
                 task_id, context_id),
            )

    def get(self, agreement_id, version):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM seller_agreement_reviews WHERE agreement_id=? AND version=?",
                (agreement_id, version),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list(self, agreement_id):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM seller_agreement_reviews WHERE agreement_id=? ORDER BY version",
                (agreement_id,),
            ).fetchall()
        return [dict(r) for r in rows]
