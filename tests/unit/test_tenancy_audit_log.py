"""The audit log is written with raw SQL, so its placeholders must be portable.

SQLite accepts ``?`` placeholders; PostgreSQL's psycopg driver does not and
reports "the query has 0 placeholders but N parameters were passed".
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql, sqlite

from verifund_control_plane.tenancy.repository import (
    audit_log_insert_statement,
)


def _params() -> dict:
    return {
        "audit_id": "796a1113-1461-4fe8-93eb-9c0021f2c9f6",
        "scope": "organization",
        "transaction_id": None,
        "organization_id": "def2289e-209c-4b7e-8ea8-dc35eb090122",
        "actor_user_id": "db032879-25c9-46c8-9f08-913a896ff319",
        "actor_type": "user",
        "action": "seller.onboarding.started",
        "resource_id": "c66f026638e24d4480e1be583a0b548c",
        "payload": "{}",
        "created_at": "2026-11-12T22:21:01.765687+00:00",
    }


def test_audit_log_insert_binds_named_parameters() -> None:
    statement = audit_log_insert_statement()

    assert statement.text.count(":") == 10
    assert "?" not in statement.text


def test_audit_log_insert_compiles_for_postgresql() -> None:
    compiled = str(
        audit_log_insert_statement().compile(dialect=postgresql.dialect())
    )

    assert "%(" in compiled
    assert "?" not in compiled


def test_audit_log_insert_compiles_for_sqlite() -> None:
    compiled = str(audit_log_insert_statement().compile(dialect=sqlite.dialect()))

    assert "?" in compiled
