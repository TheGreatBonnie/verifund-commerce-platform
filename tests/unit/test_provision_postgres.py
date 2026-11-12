from typing import Self

import pytest

from scripts.provision_postgres import (
    CHECKPOINT_ENV_VARS,
    DEFAULT_DATABASES,
    SERVICE_ENV_VARS,
    libpq_dsn,
    missing_databases,
    redact,
    service_database_url,
)

BASE = "postgresql://marketmesh:s3cret@dpg-abc.oregon-postgres.render.com/marketmesh"


def test_default_databases_cover_every_service() -> None:
    assert DEFAULT_DATABASES == (
        "buyer",
        "registry",
        "sellers",
        "verifund",
        "verifund_agent",
        "orchestrator",
    )


def test_service_env_vars_use_service_specific_names() -> None:
    assert SERVICE_ENV_VARS["buyer"] == "BUYER_DATABASE_URL"
    assert SERVICE_ENV_VARS["registry"] == "REGISTRY_DATABASE_URL"
    assert SERVICE_ENV_VARS["sellers"] == "SELLER_SHARED_DB_URL"
    assert SERVICE_ENV_VARS["verifund"] == "VERIFUND_DATABASE_URL"
    assert SERVICE_ENV_VARS["verifund_agent"] == "VERIFUND_AGENT_DATABASE_URL"
    assert SERVICE_ENV_VARS["orchestrator"] == "ORCHESTRATOR_SESSION_DB_URL"
    # No generic DATABASE_URL fallback: every service reads its own variable.
    assert "DATABASE_URL" not in SERVICE_ENV_VARS.values()


def test_service_database_url_swaps_database_and_uses_psycopg() -> None:
    url = service_database_url(BASE, "buyer")
    assert url.startswith("postgresql+psycopg://marketmesh:s3cret@")
    assert url.endswith("/buyer")


def test_service_database_url_rejects_non_postgres() -> None:
    with pytest.raises(ValueError):
        service_database_url("sqlite+aiosqlite:///./data/buyer.db", "buyer")


def test_libpq_dsn_strips_driver_suffix() -> None:
    dsn = libpq_dsn("postgresql+psycopg://u:p@host:5432/db")
    assert dsn == "postgresql://u:p@host:5432/db"


def test_redact_hides_password() -> None:
    assert "s3cret" not in redact(BASE)


def test_checkpoint_env_vars_are_postgres_urls() -> None:
    for env_var in CHECKPOINT_ENV_VARS.values():
        assert env_var.endswith("_CHECKPOINT_URL")


class _FakeCursor:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statement = statement

    def fetchall(self) -> list[tuple[str]]:
        return [(name,) for name in self._names]


class _FakeConnection:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._names)


def test_missing_databases_skips_existing() -> None:
    conn = _FakeConnection(["buyer", "registry"])
    assert missing_databases(conn, ["buyer", "registry", "sellers"]) == ["sellers"]


def test_missing_databases_returns_empty_when_all_present() -> None:
    conn = _FakeConnection(list(DEFAULT_DATABASES))
    assert missing_databases(conn, DEFAULT_DATABASES) == []
