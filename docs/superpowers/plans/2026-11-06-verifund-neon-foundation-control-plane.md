# Verifund Neon PostgreSQL — Plan 1: Foundation and Control Plane

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every SQLite runtime path in the Verifund control plane with PostgreSQL 18 on Neon, using native UUIDs, `TIMESTAMPTZ`, `JSONB`, Alembic-owned schema, per-service roles, a request-scoped unit of work, and row-level security. Ship the shared PostgreSQL foundation that the buyer, seller, registry, and agent-runtime plans will reuse.

**Architecture:** One Neon project, one database for the control plane, and four control-plane roles: `cp_migrator` owns DDL, `cp_app` serves tenant requests under RLS, `cp_auth` performs pre-tenant identity reads, and `cp_service` handles webhooks, reconciliation, and platform paths with `BYPASSRLS`. A request-scoped `UnitOfWork` owns one connection and one transaction, sets `app.tenant_id` transaction-locally, and binds itself to a context variable. Repositories never open their own transactions. PayPal and tracking HTTP calls happen only between explicit `commit()`/`begin()` boundaries.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async Core, psycopg 3, PostgreSQL 18, Alembic, Pydantic Settings, pytest/pytest-asyncio, httpx, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md`

**Program position:** This is plan 1 of 4. It delivers the shared foundation plus the complete control-plane migration. Later plans cover:
1. buyer agent (`runs`, traces, settlement projections, A2A tasks, checkpoints);
2. seller agents + registry;
3. Verifund agent + orchestrator session state.

The design's Phase 5 cutover remains a separate program-level plan after all four service plans land. This plan removes SQLite only from the control plane; buyer, seller, registry, and agent tests keep using SQLite until their plans.

---

## Global Constraints

- PostgreSQL **18** is the only supported control-plane database. No `sqlite+aiosqlite` fallback, branch, or dual-dialect code path remains in `apps/verifund_control_plane`.
- Generated entity IDs are native PostgreSQL `uuid` columns exposed to Python as strings. Use `Uuid(as_uuid=False)` and `str(uuid4())`. Business keys, provider IDs, A2A IDs, hashes, and composite keys stay `TEXT`.
- Timestamps use the shared `UTCDateTime` decorator (`DateTime(timezone=True)` + UTC ISO-8601 strings at the Python boundary). Integer cents stay integer cents.
- App-owned JSON columns use PostgreSQL `JSONB`. `requirement_declarations.submission_ids` is replaced by `requirement_declaration_submissions`.
- Schema changes happen only through Alembic. `metadata.create_all`, `create_schema()`, `PRAGMA table_info`, and runtime `ALTER TABLE` are removed.
- Every request-scoped business request uses exactly one `UnitOfWork` and one transaction. Tenant context is set with `set_config('app.tenant_id', :tenant, true)` inside that transaction.
- Never hold a transaction across a PayPal or tracking HTTP call. Commit the pending operation, call the provider, then begin a new transaction and record the result.
- RLS is enabled and forced on the tables named in the design. Missing `app.tenant_id` must match zero rows. `cp_service` is the only runtime role with `BYPASSRLS` besides `cp_auth`'s read-only identity path.
- Every test database name must end in `_test`. The harness refuses to drop or truncate any other database.
- Tests run with `uv run pytest`. Lint with `uv run ruff check .`. Do not skip PostgreSQL tests when the database is unavailable; fail loudly.
- Each task ends with a commit. Do not batch multiple tasks into one commit.
- Do not migrate local SQLite rows or checkpoints. Local `.db` files remain untouched, read-only legacy artifacts.
- Do not introduce a generic `DATABASE_URL` fallback. Each control-plane role reads its own explicit URL and fails fast when missing.

---

## File Structure

**New — shared/foundation**
- `packages/commerce_core/commerce_core/types.py` — `UTCDateTime`, `UUIDStr`, `new_uuid`.
- `tests/support/postgres.py` — test database guard, creation, role provisioning, migration runner, truncation.
- `tests/conftest.py` — session database, connection, role, and app-client fixtures.
- `apps/verifund_control_plane/verifund_control_plane/pg.py` — engine factory, retry classification, retry helper.
- `apps/verifund_control_plane/verifund_control_plane/uow.py` — `UnitOfWork`, context variable binding, `current_uow`.
- `apps/verifund_control_plane/verifund_control_plane/middleware.py` — route classification and request-scoped UoW binding.
- `apps/verifund_control_plane/verifund_control_plane/schema.py` — single SQLAlchemy metadata source for all control-plane tables.
- `apps/verifund_control_plane/verifund_control_plane/tenancy/identity_service.py` — `cp_auth` reads, `cp_service` bootstrap writes.
- `apps/verifund_control_plane/alembic.ini`, `apps/verifund_control_plane/migrations/env.py`, `script.py.mako`, `versions/`.
- `scripts/provision_control_plane_roles.py` — idempotent role/password/attribute provisioning.
- `scripts/seed_control_plane.py` — system principal, demo organizations/profiles, payment accounts; idempotent.

**New — tests**
- `tests/unit/test_postgres_dependencies.py`
- `tests/unit/test_compose_postgres.py`
- `tests/unit/test_postgres_harness.py`
- `tests/unit/test_utc_datetime.py`
- `tests/unit/test_postgres_engine.py`
- `tests/unit/test_unit_of_work.py`
- `tests/unit/test_postgres_settings.py`
- `tests/unit/test_schema_core.py`
- `tests/unit/test_schema_tenancy.py`
- `tests/unit/test_schema_agreements.py`
- `tests/integration/test_control_plane_migration.py`
- `tests/integration/test_control_plane_roles.py`
- `tests/integration/test_control_plane_rls.py`
- `tests/integration/test_control_plane_rls_matrix.py`
- `tests/integration/test_verifund_provider_boundaries.py`
- `tests/integration/test_control_plane_lifecycle_postgres.py`

**Modified**
- `pyproject.toml`, `packages/commerce_core/pyproject.toml`, `docker-compose.yml`, `.env.example`
- `apps/verifund_control_plane/verifund_control_plane/settings.py`, `app.py`, `__main__.py`
- `apps/verifund_control_plane/verifund_control_plane/repository.py`
- `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`, `identity.py`
- `apps/verifund_control_plane/verifund_control_plane/agreements/repository.py`
- `apps/verifund_control_plane/verifund_control_plane/service.py`, `reconciler.py`, `evidence.py`, `api/webhooks.py`, `api/health.py`, `paypal/fake.py`
- all control-plane tests that currently create `sqlite+aiosqlite` engines or call `create_schema()`

**Deleted at the end of this plan**
- `apps/verifund_control_plane/verifund_control_plane/db.py`
- `apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py` (replaced by `scripts/seed_control_plane.py`)

---

## Milestone 0 — Shared Foundation

### Task 1: Add the PostgreSQL dependency stack

**Files:**
- Modify: `pyproject.toml`, `packages/commerce_core/pyproject.toml`
- Test: `tests/unit/test_postgres_dependencies.py`

**Interfaces:**
- Produces: `psycopg` 3, Alembic, and `langgraph-checkpoint-postgres` importable from the workspace environment.

- [ ] **Step 1: Write the failing dependency test**

```python
# tests/unit/test_postgres_dependencies.py
from importlib.metadata import version

import alembic
import psycopg


def test_postgres_driver_is_psycopg_3() -> None:
    assert psycopg.__version__.split(".")[0] == "3"


def test_alembic_is_available() -> None:
    assert alembic.__version__


def test_langgraph_postgres_checkpointer_is_available() -> None:
    assert version("langgraph-checkpoint-postgres").split(".")[0] == "3"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_postgres_dependencies.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'psycopg'` (and missing `langgraph-checkpoint-postgres`).

- [ ] **Step 3: Add the dependencies**

In root `pyproject.toml` `[project].dependencies` add:

```toml
  "psycopg[binary,pool]>=3.2,<4",
  "alembic>=1.20,<2",
  "langgraph-checkpoint-postgres>=3.2,<4",
```

In `packages/commerce_core/pyproject.toml` `[project].dependencies` add:

```toml
  "psycopg[binary]>=3.2,<4",
```

Keep `aiosqlite` and the `a2a-sdk[sqlite]` extra for now; the other services still use SQLite until their own plans.

- [ ] **Step 4: Lock and install**

Run:

```bash
uv lock
uv sync
```

Expected: `psycopg`, `psycopg-pool`, `alembic`, and `langgraph-checkpoint-postgres` resolve without dependency conflicts.

- [ ] **Step 5: Re-run the test**

Run: `uv run pytest tests/unit/test_postgres_dependencies.py -q`

Expected: PASS, 3 tests.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock packages/commerce_core/pyproject.toml tests/unit/test_postgres_dependencies.py
git commit -m "build: add postgresql driver, alembic, and postgres checkpointer"
```

---

### Task 2: Add PostgreSQL 18 to local Compose

**Files:**
- Modify: `docker-compose.yml`, `.env.example`
- Test: `tests/unit/test_compose_postgres.py`

**Interfaces:**
- Produces: Compose service `postgres` on `127.0.0.1:55432`, database `postgres`, user `postgres`, trust auth for local test traffic, and a `pg_isready` healthcheck.

- [ ] **Step 1: Write the failing Compose test**

```python
# tests/unit/test_compose_postgres.py
from pathlib import Path

import yaml


def test_compose_defines_postgres_18_for_tests() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    service = compose["services"]["postgres"]

    assert service["image"] == "postgres:18"
    assert "127.0.0.1:55432:5432" in service["ports"]
    assert service["environment"]["POSTGRES_USER"] == "postgres"
    assert service["environment"]["POSTGRES_DB"] == "postgres"
    assert "pg_isready" in " ".join(service["healthcheck"]["test"])


def test_env_example_documents_the_test_database() -> None:
    text = Path(".env.example").read_text()
    assert "TEST_POSTGRES_ADMIN_URL=" in text
    assert "VERIFUND_DATABASE_URL_UNPOOLED=" in text
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_compose_postgres.py -q`

Expected: FAIL with `KeyError: 'postgres'`.

- [ ] **Step 3: Add the Compose service**

Add under `services:` in `docker-compose.yml`:

```yaml
  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
      POSTGRES_HOST_AUTH_METHOD: trust
    command:
      - postgres
      - -c
      - max_connections=200
    ports:
      - "127.0.0.1:55432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 2s
      timeout: 3s
      retries: 30
    volumes:
      - postgres-data:/var/lib/postgresql/data
```

Add `postgres-data:` under the top-level `volumes:` block.

Add to `.env.example`:

```dotenv
# PostgreSQL 18 for control-plane development and tests.
# The test harness refuses database names that do not end in _test.
TEST_POSTGRES_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres

# Control-plane runtime roles. Never use neondb_owner at runtime.
VERIFUND_DATABASE_URL=postgresql+psycopg://cp_app:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_AUTH_DATABASE_URL=postgresql+psycopg://cp_auth:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_SERVICE_DATABASE_URL=postgresql+psycopg://cp_service:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_DATABASE_URL_UNPOOLED=postgresql+psycopg://cp_migrator:change-me@127.0.0.1:55432/verifund_control_plane
```

- [ ] **Step 4: Start PostgreSQL and verify health**

Run:

```bash
docker compose up -d postgres
docker compose exec postgres pg_isready -U postgres -d postgres
```

Expected: `... accepting connections`.

- [ ] **Step 5: Re-run the test**

Run: `uv run pytest tests/unit/test_compose_postgres.py -q`

Expected: PASS, 2 tests.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example tests/unit/test_compose_postgres.py
git commit -m "build: add postgresql 18 test service"
```

---

### Task 3: Build the PostgreSQL test database harness

**Files:**
- Create: `tests/support/postgres.py`, `tests/conftest.py`
- Test: `tests/unit/test_postgres_harness.py`

**Interfaces:**
- Produces:
  - `assert_test_database(name: str) -> None`
  - `TestDatabase` dataclass with `name`, `admin_url`, `migrator_url`, `app_url`, `auth_url`, `service_url`
  - `create_test_database(name) -> TestDatabase`
  - `drop_test_database(database) -> None`
  - `upgrade_database(database) -> None`
  - `truncate_all(database) -> None`
  - pytest fixtures: `control_plane_database` (session), `db_conn` (service-role transaction, rollback), `clean_control_plane`.
- Consumes: PostgreSQL 18 from Task 2, Alembic from Task 1.

- [ ] **Step 1: Write the failing harness test**

```python
# tests/unit/test_postgres_harness.py
import pytest
from sqlalchemy import text

from tests.support.postgres import assert_test_database, create_test_database, drop_test_database


def test_database_name_guard_rejects_non_test_names() -> None:
    with pytest.raises(ValueError, match="_test"):
        assert_test_database("verifund_control_plane")


async def test_harness_creates_a_postgres_18_database(control_plane_database) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(control_plane_database.service_url)
    async with engine.connect() as conn:
        version = await conn.scalar(text("show server_version"))
    await engine.dispose()
    assert str(version).startswith("18.")


async def test_db_conn_is_transactional_and_uses_the_service_role(db_conn) -> None:
    role = await db_conn.scalar(text("select current_user"))
    assert role == "cp_service"
    assert (await db_conn.execute(text("select 1"))).scalar_one() == 1
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_postgres_harness.py -q`

Expected: FAIL with `ModuleNotFoundError: tests.support.postgres`.

- [ ] **Step 3: Implement the harness**

```python
# tests/support/postgres.py
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ADMIN_URL = os.environ.get(
    "TEST_POSTGRES_ADMIN_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres",
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "apps/verifund_control_plane/alembic.ini"
ROLES = ("cp_migrator", "cp_app", "cp_auth", "cp_service")
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*_test$")


def assert_test_database(name: str) -> None:
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"refusing to touch database {name!r}: name must match {_SAFE_NAME.pattern}")


@dataclass(frozen=True)
class TestDatabase:
    name: str
    admin_url: str

    def _url_for(self, role: str):
        return make_url(self.admin_url).set(username=role, password=None, database=self.name)

    @property
    def migrator_url(self) -> str:
        return str(self._url_for("cp_migrator"))

    @property
    def app_url(self) -> str:
        return str(self._url_for("cp_app"))

    @property
    def auth_url(self) -> str:
        return str(self._url_for("cp_auth"))

    @property
    def service_url(self) -> str:
        return str(self._url_for("cp_service"))


async def _admin_execute(sql: str) -> None:
    engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with engine.connect() as conn:
        await conn.execute(text(sql))
    await engine.dispose()


async def _ensure_roles() -> None:
    for role in ROLES:
        attrs = "BYPASSRLS" if role in {"cp_auth", "cp_service"} else "NOBYPASSRLS"
        await _admin_execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN;
              END IF;
            END
            $$;
            ALTER ROLE {role} LOGIN {attrs};
            """
        )


async def create_test_database(name: str = "verifund_control_plane_test") -> TestDatabase:
    assert_test_database(name)
    await _ensure_roles()
    await _admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await _admin_execute(f'CREATE DATABASE "{name}" OWNER cp_migrator')
    await _admin_execute(f'GRANT CONNECT ON DATABASE "{name}" TO cp_app, cp_auth, cp_service')
    return TestDatabase(name=name, admin_url=ADMIN_URL)


async def drop_test_database(database: TestDatabase) -> None:
    assert_test_database(database.name)
    await _admin_execute(f'DROP DATABASE IF EXISTS "{database.name}" WITH (FORCE)')


def _upgrade_sync(database: TestDatabase) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database.migrator_url)
    command.upgrade(config, "head")


async def upgrade_database(database: TestDatabase) -> None:
    await asyncio.to_thread(_upgrade_sync, database)


async def truncate_all(database: TestDatabase) -> None:
    assert_test_database(database.name)
    from verifund_control_plane.schema import metadata

    tables = ", ".join(f'"{table.name}"' for table in metadata.sorted_tables)
    if not tables:
        return
    engine = create_async_engine(database.migrator_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()
```

```python
# tests/conftest.py
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.support.postgres import (
    TestDatabase,
    create_test_database,
    drop_test_database,
    truncate_all,
    upgrade_database,
)


@pytest.fixture(scope="session")
async def control_plane_database() -> TestDatabase:
    database = await create_test_database("verifund_control_plane_test")
    await upgrade_database(database)
    yield database
    await drop_test_database(database)


@pytest.fixture
async def clean_control_plane(control_plane_database: TestDatabase) -> None:
    await truncate_all(control_plane_database)


@pytest.fixture
async def db_conn(control_plane_database: TestDatabase):
    engine = create_async_engine(control_plane_database.service_url, poolclass=NullPool)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()
    await engine.dispose()
```

The `db_conn` fixture intentionally uses `cp_service`. Repository behavior tests do not need tenant context; RLS tests use explicit `cp_app`/`cp_auth` fixtures in the RLS tasks.

- [ ] **Step 4: Verify the harness**

Run:

```bash
docker compose up -d postgres
uv run pytest tests/unit/test_postgres_harness.py -q
```

Expected: PASS, 3 tests. The first run creates `verifund_control_plane_test`, runs Alembic to head, and drops it at session end.

- [ ] **Step 5: Commit**

```bash
git add tests/support/postgres.py tests/conftest.py tests/unit/test_postgres_harness.py
git commit -m "test: add postgresql 18 database harness"
```

---

### Task 4: Add `UTCDateTime`, `UUIDStr`, and `new_uuid` to commerce_core

**Files:**
- Create: `packages/commerce_core/commerce_core/types.py`
- Modify: `packages/commerce_core/commerce_core/__init__.py`
- Test: `tests/unit/test_utc_datetime.py`

**Interfaces:**
- Produces:
  - `UTCDateTime` SQLAlchemy `TypeDecorator` with `impl = DateTime(timezone=True)` and `cache_ok = True`.
  - `UUIDStr = Uuid(as_uuid=False)`.
  - `new_uuid() -> str` returning `str(uuid4())`.
- Behavior: binds accept aware `datetime` or ISO-8601 string; naive datetimes raise `ValueError`; results are UTC strings ending in `Z`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_utc_datetime.py
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, MetaData, Table, insert, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from commerce_core.types import UTCDateTime, UUIDStr, new_uuid


async def test_utc_datetime_round_trips_as_utc_string(db_conn) -> None:
    table = Table(
        "utc_probe",
        MetaData(),
        Column("id", UUIDStr, primary_key=True),
        Column("at", UTCDateTime(), nullable=False),
    )
    await db_conn.run_sync(table.create)
    identifier = new_uuid()
    aware = datetime(2026, 11, 6, 14, 30, tzinfo=timezone(timedelta(hours=2)))
    await db_conn.execute(insert(table).values(id=identifier, at=aware))
    stored = await db_conn.scalar(select(table.c.at))
    assert stored == "2026-11-06T12:30:00Z"


async def test_utc_datetime_accepts_iso_strings(db_conn) -> None:
    table = Table(
        "utc_probe_str",
        MetaData(),
        Column("id", UUIDStr, primary_key=True),
        Column("at", UTCDateTime(), nullable=False),
    )
    await db_conn.run_sync(table.create)
    await db_conn.execute(
        insert(table).values(id=new_uuid(), at="2026-11-06T12:30:00+00:00")
    )
    assert await db_conn.scalar(select(table.c.at)) == "2026-11-06T12:30:00Z"


async def test_utc_datetime_rejects_naive_datetimes(db_conn) -> None:
    table = Table(
        "utc_probe_naive",
        MetaData(),
        Column("id", UUIDStr, primary_key=True),
        Column("at", UTCDateTime(), nullable=False),
    )
    await db_conn.run_sync(table.create)
    with pytest.raises(ValueError, match="timezone"):
        await db_conn.execute(
            insert(table).values(id=new_uuid(), at=datetime(2026, 11, 6, 12, 30))
        )


def test_utc_datetime_compiles_to_timestamptz() -> None:
    table = Table("utc_compile", MetaData(), Column("at", UTCDateTime()))
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "TIMESTAMP WITH TIME ZONE" in ddl


def test_uuid_str_compiles_to_native_uuid_and_returns_strings(db_conn) -> None:
    table = Table("uuid_compile", MetaData(), Column("id", UUIDStr, primary_key=True))
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "UUID" in ddl
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_utc_datetime.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'commerce_core.types'`.

- [ ] **Step 3: Implement the types**

```python
# packages/commerce_core/commerce_core/types.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, TypeDecorator, Uuid

UUIDStr = Uuid(as_uuid=False)


def new_uuid() -> str:
    return str(uuid4())


class UTCDateTime(TypeDecorator[str]):
    """Store TIMESTAMPTZ and expose UTC ISO-8601 strings to Python."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | str | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("UTCDateTime values must be datetime or ISO-8601 strings")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
```

Update `packages/commerce_core/commerce_core/__init__.py` to export the three names:

```python
from commerce_core.types import UTCDateTime, UUIDStr, new_uuid

__all__ = [*__all__, "UTCDateTime", "UUIDStr", "new_uuid"]
```

If `__all__` does not exist, add it with the three names.

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_utc_datetime.py -q`

Expected: PASS, 5 tests. The first three create temporary tables inside `db_conn`; PostgreSQL rolls the DDL back with the fixture transaction.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/types.py packages/commerce_core/commerce_core/__init__.py tests/unit/test_utc_datetime.py
git commit -m "feat: add utc datetime and uuid sqlalchemy types"
```

### Task 5: Add the PostgreSQL engine factory and retry helpers

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/pg.py`
- Test: `tests/unit/test_postgres_engine.py`

**Interfaces:**
- Produces:
  - `create_postgres_engine(url: str, *, application_name: str = "verifund-control-plane", **overrides) -> AsyncEngine`
  - `is_retryable(exc: BaseException) -> bool` for SQLSTATE `40001` and `40P01`
  - `run_with_retry(operation, *, attempts=3, base_delay=0.05)`
- Consumes: psycopg 3, SQLAlchemy async.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_postgres_engine.py
import pytest
from psycopg.errors import DeadlockDetected, SerializationFailure
from sqlalchemy import text

from verifund_control_plane.pg import (
    create_postgres_engine,
    is_retryable,
    run_with_retry,
)


def test_engine_factory_rejects_non_postgres_urls() -> None:
    with pytest.raises(ValueError, match="postgresql\\+psycopg"):
        create_postgres_engine("sqlite+aiosqlite:///./data/verifund.db")


async def test_engine_connects_with_prepare_threshold_disabled(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with engine.connect() as conn:
        assert (await conn.execute(text("select 1"))).scalar_one() == 1
    await engine.dispose()


def test_retry_classification() -> None:
    assert is_retryable(SerializationFailure("serialization failure"))
    assert is_retryable(DeadlockDetected("deadlock detected"))
    assert not is_retryable(ValueError("nope"))


async def test_run_with_retry_retries_serialization_failures() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SerializationFailure("serialization failure")
        return "ok"

    assert await run_with_retry(operation, attempts=3, base_delay=0) == "ok"
    assert calls == 2
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_postgres_engine.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane.pg'`.

- [ ] **Step 3: Implement the engine factory and retry helper**

```python
# apps/verifund_control_plane/verifund_control_plane/pg.py
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

T = TypeVar("T")
RETRYABLE_SQLSTATES = {"40001", "40P01"}


def create_postgres_engine(
    url: str,
    *,
    application_name: str = "verifund-control-plane",
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 300,
) -> AsyncEngine:
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError(
            "control-plane URLs must use postgresql+psycopg://; got "
            f"{url.split(':', 1)[0]}"
        )
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=pool_recycle,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        connect_args={
            "prepare_threshold": None,
            "application_name": application_name,
        },
    )


def is_retryable(exc: BaseException) -> bool:
    original = getattr(exc, "orig", exc)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate in RETRYABLE_SQLSTATES


async def run_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
) -> T:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except BaseException as exc:
            if not is_retryable(exc) or attempt == attempts - 1:
                raise
            last_error = exc
            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay * (0.5 + random.random()))
    raise last_error  # pragma: no cover - loop always returns or raises
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_postgres_engine.py -q`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/pg.py tests/unit/test_postgres_engine.py
git commit -m "feat: add postgres engine factory and retry helpers"
```

---

### Task 6: Implement the transaction-scoped `UnitOfWork`

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/uow.py`
- Test: `tests/unit/test_unit_of_work.py`

**Interfaces:**
- Produces:
  - `UnitOfWork(engine, *, tenant_id: str | None = None, user_id: str | None = None)`
  - `uow.connection`, `uow.in_transaction`
  - `await uow.begin()`, `await uow.commit()`, `await uow.rollback()`
  - `bind_uow(uow) -> Token`, `reset_uow(token)`, `current_uow() -> UnitOfWork`
- Behavior:
  - `begin()` starts a transaction and applies `set_config('app.tenant_id', ..., true)` plus `set_config('app.user_id', ..., true)` when a tenant is present.
  - `commit()`/`rollback()` clear the active transaction; the next `begin()` re-applies tenant context.
  - `__aexit__` rolls back on exception, commits otherwise, then closes the connection.
  - No tenant set means `current_setting('app.tenant_id', true)` is `NULL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_unit_of_work.py
import pytest
from sqlalchemy import text

from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.uow import (
    UnitOfWork,
    bind_uow,
    current_uow,
    reset_uow,
)


async def _tenant_setting(conn) -> str | None:
    return await conn.scalar(text("select current_setting('app.tenant_id', true)"))


async def test_begin_sets_transaction_local_tenant(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine, tenant_id="org-a", user_id="user-a") as uow:
        assert uow.in_transaction is True
        assert await _tenant_setting(uow.connection) == "org-a"
        assert await uow.connection.scalar(
            text("select current_setting('app.user_id', true)")
        ) == "user-a"
    await engine.dispose()


async def test_commit_and_begin_reapply_tenant_context(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine, tenant_id="org-a") as uow:
        await uow.commit()
        assert uow.in_transaction is False
        async with engine.connect() as probe:
            assert await _tenant_setting(probe) is None
        await uow.begin()
        assert await _tenant_setting(uow.connection) == "org-a"
    await engine.dispose()


async def test_missing_tenant_fails_closed(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        assert await _tenant_setting(uow.connection) is None
    await engine.dispose()


async def test_exception_rolls_back(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    with pytest.raises(RuntimeError, match="boom"):
        async with UnitOfWork(engine) as uow:
            await uow.connection.execute(text("create table uow_rollback_probe (id int)"))
            raise RuntimeError("boom")
    async with engine.connect() as conn:
        exists = await conn.scalar(text("select to_regclass('public.uow_rollback_probe')"))
        assert exists is None
    await engine.dispose()


async def test_tenant_context_does_not_leak_on_a_pooled_connection(control_plane_database) -> None:
    engine = create_postgres_engine(
        control_plane_database.service_url, pool_size=1, max_overflow=0
    )
    async with UnitOfWork(engine, tenant_id="org-a") as uow:
        assert await _tenant_setting(uow.connection) == "org-a"
    async with UnitOfWork(engine) as uow:
        assert await _tenant_setting(uow.connection) is None
    await engine.dispose()


async def test_context_variable_binding(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    with pytest.raises(RuntimeError, match="no active unit of work"):
        current_uow()
    async with UnitOfWork(engine, tenant_id="org-a") as uow:
        token = bind_uow(uow)
        try:
            assert current_uow() is uow
        finally:
            reset_uow(token)
    with pytest.raises(RuntimeError, match="no active unit of work"):
        current_uow()
    await engine.dispose()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_unit_of_work.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane.uow'`.

- [ ] **Step 3: Implement the unit of work**

```python
# apps/verifund_control_plane/verifund_control_plane/uow.py
from __future__ import annotations

from contextvars import ContextVar, Token
from types import TracebackType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

_current_uow: ContextVar[UnitOfWork | None] = ContextVar("verifund_uow", default=None)


class UnitOfWork:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.engine = engine
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None

    @property
    def connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError("unit of work has not started")
        return self._connection

    @property
    def in_transaction(self) -> bool:
        return self._transaction is not None

    async def __aenter__(self) -> UnitOfWork:
        self._connection = await self.engine.connect()
        await self.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._transaction is not None:
                if exc_type is None:
                    await self._transaction.commit()
                else:
                    await self._transaction.rollback()
                self._transaction = None
        finally:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None

    async def begin(self) -> None:
        if self._connection is None:
            raise RuntimeError("unit of work has not started")
        if self._transaction is not None:
            raise RuntimeError("a transaction is already active")
        self._transaction = await self._connection.begin()
        if self.tenant_id is not None:
            await self._connection.execute(
                text("select set_config('app.tenant_id', :value, true)"),
                {"value": self.tenant_id},
            )
            await self._connection.execute(
                text("select set_config('app.user_id', :value, true)"),
                {"value": self.user_id or ""},
            )

    async def commit(self) -> None:
        if self._transaction is None:
            return
        await self._transaction.commit()
        self._transaction = None

    async def rollback(self) -> None:
        if self._transaction is None:
            return
        await self._transaction.rollback()
        self._transaction = None


def bind_uow(uow: UnitOfWork) -> Token[UnitOfWork | None]:
    return _current_uow.set(uow)


def reset_uow(token: Token[UnitOfWork | None]) -> None:
    _current_uow.reset(token)


def current_uow() -> UnitOfWork:
    uow = _current_uow.get()
    if uow is None:
        raise RuntimeError("no active unit of work")
    return uow
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_unit_of_work.py -q`

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/uow.py tests/unit/test_unit_of_work.py
git commit -m "feat: add request-scoped postgres unit of work"
```

---

### Task 7: Require explicit PostgreSQL URLs and pool settings

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Test: `tests/unit/test_postgres_settings.py`

**Interfaces:**
- Produces settings fields:
  - `database_url` (`VERIFUND_DATABASE_URL`, `cp_app`, pooled)
  - `auth_database_url` (`VERIFUND_AUTH_DATABASE_URL`, `cp_auth`, pooled)
  - `service_database_url` (`VERIFUND_SERVICE_DATABASE_URL`, `cp_service`, pooled)
  - `database_url_unpooled` (`VERIFUND_DATABASE_URL_UNPOOLED`, `cp_migrator`, direct)
  - `db_pool_size=5`, `db_max_overflow=10`, `db_pool_timeout=30`, `db_pool_recycle=300`
- Behavior: all four URLs are required and must start with `postgresql+psycopg://`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_postgres_settings.py
import pytest
from pydantic import ValidationError

from verifund_control_plane.settings import Settings

BASE = {
    "database_url": "postgresql+psycopg://cp_app@localhost/db",
    "auth_database_url": "postgresql+psycopg://cp_auth@localhost/db",
    "service_database_url": "postgresql+psycopg://cp_service@localhost/db",
    "database_url_unpooled": "postgresql+psycopg://cp_migrator@localhost/db",
}


def test_postgres_urls_are_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mode="fake")


def test_sqlite_urls_are_rejected() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings(
            _env_file=None,
            mode="fake",
            **{**BASE, "database_url": "sqlite+aiosqlite:///./data/verifund.db"},
        )


def test_pool_defaults_are_explicit() -> None:
    settings = Settings(_env_file=None, mode="fake", **BASE)
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30
    assert settings.db_pool_recycle == 300
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_postgres_settings.py -q`

Expected: FAIL because `Settings` still defaults to SQLite and has no auth/service URL fields.

- [ ] **Step 3: Update settings**

Add `field_validator` to the Pydantic imports and replace the `database_url` block with:

```python
    database_url: str = Field(validation_alias="VERIFUND_DATABASE_URL")
    auth_database_url: str = Field(validation_alias="VERIFUND_AUTH_DATABASE_URL")
    service_database_url: str = Field(validation_alias="VERIFUND_SERVICE_DATABASE_URL")
    database_url_unpooled: str = Field(
        validation_alias="VERIFUND_DATABASE_URL_UNPOOLED"
    )
    db_pool_size: int = Field(default=5, validation_alias="VERIFUND_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, validation_alias="VERIFUND_DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, validation_alias="VERIFUND_DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=300, validation_alias="VERIFUND_DB_POOL_RECYCLE")
```

Add a validator inside `Settings`:

```python
    @field_validator(
        "database_url",
        "auth_database_url",
        "service_database_url",
        "database_url_unpooled",
    )
    @classmethod
    def _require_psycopg_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "database URLs must use postgresql+psycopg://; "
                "SQLite and generic DATABASE_URL fallbacks are not supported"
            )
        return value
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_postgres_settings.py -q`

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/settings.py tests/unit/test_postgres_settings.py
git commit -m "feat: require explicit postgres control-plane urls"
```

---

### Task 8: Add Alembic scaffolding and a fail-fast revision check

**Files:**
- Create: `apps/verifund_control_plane/alembic.ini`
- Create: `apps/verifund_control_plane/migrations/env.py`
- Create: `apps/verifund_control_plane/migrations/script.py.mako`
- Create: `apps/verifund_control_plane/migrations/versions/.gitkeep`
- Create: `apps/verifund_control_plane/verifund_control_plane/schema.py` (empty metadata for now; populated in Task 9)
- Test: `tests/unit/test_schema_revision.py`

**Interfaces:**
- Produces:
  - `schema.metadata` imported by `env.py`.
  - `schema.HEAD_REVISION` and `assert_schema_revision(conn, expected=None)`.
  - Alembic config whose URL comes from `config.get_main_option("sqlalchemy.url")` or `VERIFUND_DATABASE_URL_UNPOOLED`.
- Consumes: `create_postgres_engine` is not used by Alembic; the migration environment uses `postgresql+psycopg` directly.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schema_revision.py
import pytest
from alembic.config import Config
from sqlalchemy import text

from verifund_control_plane.schema import HEAD_REVISION, assert_schema_revision


def test_alembic_config_points_at_the_control_plane_migrations() -> None:
    config = Config("apps/verifund_control_plane/alembic.ini")
    assert config.get_main_option("script_location").endswith("migrations")


async def test_revision_check_fails_when_database_is_unmigrated(db_conn) -> None:
    with pytest.raises(RuntimeError, match="not migrated"):
        await assert_schema_revision(db_conn)


async def test_revision_check_accepts_the_head_revision(db_conn) -> None:
    await db_conn.execute(
        text("create table alembic_version (version_num varchar(32) primary key)")
    )
    await db_conn.execute(
        text("insert into alembic_version (version_num) values (:rev)"),
        {"rev": HEAD_REVISION},
    )
    await assert_schema_revision(db_conn)


async def test_revision_check_rejects_a_stale_revision(db_conn) -> None:
    await db_conn.execute(
        text("create table alembic_version (version_num varchar(32) primary key)")
    )
    await db_conn.execute(text("insert into alembic_version (version_num) values ('0000')"))
    with pytest.raises(RuntimeError, match=HEAD_REVISION):
        await assert_schema_revision(db_conn)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_schema_revision.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane.schema'`.

- [ ] **Step 3: Add the Alembic configuration**

```ini
# apps/verifund_control_plane/alembic.ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = %(here)s/../..
path_separator = os
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

```python
# apps/verifund_control_plane/migrations/env.py
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from verifund_control_plane.schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or os.environ[
    "VERIFUND_DATABASE_URL_UNPOOLED"
]
config.set_main_option("sqlalchemy.url", url)
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

```mako
# apps/verifund_control_plane/migrations/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Add the schema revision check**

```python
# apps/verifund_control_plane/verifund_control_plane/schema.py
from __future__ import annotations

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncConnection

metadata = MetaData()
HEAD_REVISION = "0001_control_plane_schema"


async def assert_schema_revision(
    conn: AsyncConnection, expected: str | None = None
) -> None:
    expected = expected or HEAD_REVISION
    exists = await conn.scalar(text("select to_regclass('public.alembic_version')"))
    if exists is None:
        raise RuntimeError("database is not migrated; run alembic upgrade head")
    current = await conn.scalar(text("select version_num from alembic_version"))
    if current != expected:
        raise RuntimeError(
            f"database revision {current!r} does not match expected {expected!r}; "
            "run alembic upgrade head before starting the service"
        )
```

- [ ] **Step 5: Re-run the test**

Run: `uv run pytest tests/unit/test_schema_revision.py -q`

Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/alembic.ini apps/verifund_control_plane/migrations apps/verifund_control_plane/verifund_control_plane/schema.py tests/unit/test_schema_revision.py
git commit -m "feat: add alembic scaffolding and schema revision check"
```

---

## Milestone 1 — Control-Plane Schema

### Task 9: Define the core transaction schema metadata

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py`
- Test: `tests/unit/test_schema_core.py`

**Interfaces:**
- Produces table objects on `schema.metadata` for:
  `transactions`, `transaction_events`, `ledger_entries`, `evidence`, `evidence_submissions`, `requirement_declarations`, `requirement_declaration_submissions`, `provider_operations`, `webhook_events`, `payout_items`, `idempotency_keys`, `seller_tokens`, `buyer_tokens`, `invitation_tokens`, `checkout_links`, `receipts`, `audit_log`, `fake_orders`, `reconciler_runs`.
- Consumes: `UTCDateTime`, `UUIDStr` from `commerce_core.types`.
- Rule: copy every column definition from the existing `Repository._define_tables()` in `repository.py`, then apply only the transformations below.

**Type transformations for this task**

| Existing column | New type |
|---|---|
| `transactions.transaction_id` | `UUIDStr` |
| `transactions.buyer_organization_id`, `seller_organization_id` | `UUIDStr` nullable, FK `organizations.id` |
| `transactions.agreement_id` | `UUIDStr`, deferrable FK added in Task 11 |
| every `transactions.*` JSON column | `JSONB` |
| `transactions.created_at`, `updated_at` | `UTCDateTime` |
| `transaction_events.payload` | `JSONB` |
| `transaction_events.created_at` | `UTCDateTime` |
| `ledger_entries.entry_id` | `UUIDStr` |
| `ledger_entries.created_at` | `UTCDateTime` |
| `evidence.evidence_id` | `UUIDStr` |
| `evidence.organization_id` | `UUIDStr` nullable, FK `organizations.id` |
| `evidence.captured_at`, `created_at` | `UTCDateTime` |
| `evidence_submissions.submission_id` | `UUIDStr` |
| `evidence_submissions.created_at` | `UTCDateTime` |
| `requirement_declarations.declaration_id` | `UUIDStr` |
| `requirement_declarations.declared_at` | `UTCDateTime` |
| `requirement_declarations.submission_ids` | **remove**; join table below |
| `provider_operations.operation_id` | `UUIDStr` |
| `provider_operations.request`, `response` | `JSONB` |
| `provider_operations.created_at`, `updated_at` | `UTCDateTime` |
| `webhook_events.payload` | `JSONB` |
| `webhook_events.verified` | `Boolean`, `server_default=false()` |
| `webhook_events.received_at`, `processed_at` | `UTCDateTime` |
| `payout_items.item_id` | `UUIDStr` |
| `payout_items.raw` | `JSONB` |
| `payout_items.created_at`, `updated_at` | `UTCDateTime` |
| `idempotency_keys.response` | `JSONB` |
| `idempotency_keys.created_at` | `UTCDateTime` |
| `seller_tokens.organization_id`, `buyer_tokens.organization_id`, `checkout_links.organization_id` | `UUIDStr` nullable |
| `seller_tokens.scopes`, `buyer_tokens.scopes`, `invitation_tokens.scopes` | `JSONB` |
| `seller_tokens.expires_at`, `revoked_at`, `created_at` | `UTCDateTime` |
| `buyer_tokens.expires_at`, `revoked_at`, `created_at` | `UTCDateTime` |
| `invitation_tokens.expires_at`, `used_at`, `revoked_at`, `created_at` | `UTCDateTime` |
| `checkout_links.jti` | `UUIDStr` |
| `checkout_links.expires_at`, `used_at`, `created_at` | `UTCDateTime` |
| `receipts.payload` | `JSONB` |
| `receipts.created_at` | `UTCDateTime` |
| `audit_log.audit_id` | `UUIDStr` |
| `audit_log.transaction_id`, `organization_id`, `actor_user_id` | `UUIDStr` nullable |
| `audit_log.payload` | `JSONB` |
| `audit_log.created_at` | `UTCDateTime` |
| `fake_orders.raw` | `JSONB` |
| `fake_orders.created_at`, `updated_at` | `UTCDateTime` |
| `reconciler_runs.run_id` | `UUIDStr` |
| `reconciler_runs.stats` | `JSONB` |
| `reconciler_runs.started_at`, `finished_at` | `UTCDateTime` |
| all `transaction_id` child columns | `UUIDStr`, FK `transactions.transaction_id` `ON DELETE RESTRICT` |

Keep these columns `TEXT`: `run_id`, `buyer_id`, `seller_id`, `offer_id`, `state`, `currency`, `agreement_hash`, `provider_id`, `idempotency_key`, `jti_hash`, `payload_hash`, `sha256`, `sender_item_id`, `batch_id`, `seller_email`, `storage_key`, `media_type`, `original_filename`, all token/scopes metadata other than the JSONB scopes column, and all actor text.

- [ ] **Step 1: Write the failing core-schema test**

```python
# tests/unit/test_schema_core.py
from sqlalchemy import Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable

from commerce_core.types import UTCDateTime
from verifund_control_plane import schema


def _compile(table) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))


def test_transaction_uses_uuid_jsonb_and_timestamptz() -> None:
    table = schema.transactions
    assert isinstance(table.c.transaction_id.type, Uuid)
    assert table.c.transaction_id.type.as_uuid is False
    assert isinstance(table.c.funding.type, JSONB)
    assert isinstance(table.c.deadlines.type, JSONB)
    assert isinstance(table.c.created_at.type, UTCDateTime)
    ddl = _compile(table)
    assert "transaction_id UUID NOT NULL" in ddl
    assert "funding JSONB" in ddl
    assert "created_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl


def test_generated_child_ids_are_uuid_and_business_ids_stay_text() -> None:
    assert isinstance(schema.evidence.c.evidence_id.type, Uuid)
    assert isinstance(schema.ledger_entries.c.entry_id.type, Uuid)
    assert isinstance(schema.payout_items.c.item_id.type, Uuid)
    assert isinstance(schema.provider_operations.c.operation_id.type, Uuid)
    assert isinstance(schema.audit_log.c.audit_id.type, Uuid)
    assert not isinstance(schema.evidence.c.sha256.type, Uuid)
    assert not isinstance(schema.transactions.c.seller_id.type, Uuid)
    assert not isinstance(schema.transactions.c.run_id.type, Uuid)


def test_requirement_declarations_use_a_join_table() -> None:
    assert "submission_ids" not in schema.requirement_declarations.c
    join = schema.requirement_declaration_submissions
    assert set(join.c.keys()) == {"declaration_id", "submission_id"}
    fk_targets = {
        fk.target_fullname for fk in join.foreign_keys
    }
    assert fk_targets == {
        "requirement_declarations.declaration_id",
        "evidence_submissions.submission_id",
    }


def test_money_and_state_constraints_exist() -> None:
    names = {constraint.name for constraint in schema.transactions.constraints}
    assert "ck_transactions_amount_nonnegative" in names
    assert "ck_transactions_version_nonnegative" in names
    assert "ck_transactions_currency_shape" in names
    assert "ck_transactions_state" in names
    assert isinstance(schema.webhook_events.c.verified.type, postgresql.BOOLEAN)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_schema_core.py -q`

Expected: FAIL with `AttributeError: module 'verifund_control_plane.schema' has no attribute 'transactions'`.

- [ ] **Step 3: Implement the core metadata**

Start `schema.py` with the imports and helpers:

```python
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection
from verifund_contracts import TransactionState

from commerce_core.types import UTCDateTime, UUIDStr

metadata = MetaData()
HEAD_REVISION = "0001_control_plane_schema"


def _state_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    rendered = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({rendered})", name=name)


TRANSACTION_STATES = tuple(state.value for state in TransactionState)
```

Define `transactions` exactly as follows (copy the remaining columns from the current table definition and change only their types):

```python
transactions = Table(
    "transactions",
    metadata,
    Column("transaction_id", UUIDStr, primary_key=True),
    Column("run_id", String, nullable=False, index=True),
    Column("buyer_id", String, nullable=False),
    Column("seller_id", String, nullable=False, index=True),
    Column("buyer_organization_id", UUIDStr, nullable=True, index=True),
    Column("seller_organization_id", UUIDStr, nullable=True, index=True),
    Column("offer_id", String, nullable=False),
    Column("state", String, nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("last_seq", Integer, nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String, nullable=False),
    Column("agreement_id", UUIDStr, nullable=False),
    Column("agreement_hash", String, nullable=False),
    Column("agreement_version", Integer, nullable=False),
    Column("buyer_agent_review", JSONB, nullable=True),
    Column("seller_decision", JSONB, nullable=True),
    Column("approval", JSONB, nullable=True),
    Column("cancellation", JSONB, nullable=True),
    Column("funding", JSONB, nullable=True),
    Column("purchase_order", JSONB, nullable=True),
    Column("evidence_summary", JSONB, nullable=True),
    Column("verification", JSONB, nullable=True),
    Column("dispute", JSONB, nullable=True),
    Column("payout", JSONB, nullable=True),
    Column("tracker", JSONB, nullable=True),
    Column("receipt", JSONB, nullable=True),
    Column("deadlines", JSONB, nullable=False),
    Column("last_error", JSONB, nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    CheckConstraint("amount_cents >= 0", name="ck_transactions_amount_nonnegative"),
    CheckConstraint("version >= 0", name="ck_transactions_version_nonnegative"),
    CheckConstraint("last_seq >= 0", name="ck_transactions_last_seq_nonnegative"),
    CheckConstraint(
        "agreement_version >= 0", name="ck_transactions_agreement_version_nonnegative"
    ),
    CheckConstraint(
        "char_length(currency) = 3 AND currency = upper(currency)",
        name="ck_transactions_currency_shape",
    ),
    _state_check("state", TRANSACTION_STATES, "ck_transactions_state"),
)
```

Define the declarations and join table as follows:

```python
requirement_declarations = Table(
    "requirement_declarations",
    metadata,
    Column("declaration_id", UUIDStr, primary_key=True),
    Column(
        "transaction_id",
        UUIDStr,
        ForeignKey("transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    Column("requirement_id", String, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("actor", String, nullable=False),
    Column("declared_at", UTCDateTime, nullable=False),
    UniqueConstraint(
        "transaction_id",
        "requirement_id",
        "attempt",
        name="uq_declaration_txn_req_attempt",
    ),
    CheckConstraint("attempt >= 0", name="ck_declarations_attempt_nonnegative"),
)

requirement_declaration_submissions = Table(
    "requirement_declaration_submissions",
    metadata,
    Column(
        "declaration_id",
        UUIDStr,
        ForeignKey("requirement_declarations.declaration_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "submission_id",
        UUIDStr,
        ForeignKey("evidence_submissions.submission_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)
```

Apply the same UUID/JSONB/UTCDateTime/FK/check treatment to the remaining core tables. Use these exact foreign keys:
- `transaction_events.transaction_id` → `transactions.transaction_id` `ON DELETE RESTRICT`.
- `ledger_entries.transaction_id` → `transactions.transaction_id` `ON DELETE RESTRICT`.
- `evidence.transaction_id` → `transactions.transaction_id` `ON DELETE RESTRICT`.
- `evidence_submissions.transaction_id` → `transactions.transaction_id`; `.evidence_id` → `evidence.evidence_id` (`ON DELETE RESTRICT`).
- `provider_operations.transaction_id`, `payout_items.transaction_id`, `receipts.transaction_id`, `fake_orders.transaction_id` → `transactions.transaction_id` (`ON DELETE RESTRICT`).
- `seller_tokens.transaction_id`, `buyer_tokens.transaction_id`, `invitation_tokens.transaction_id`, `checkout_links.transaction_id` → `transactions.transaction_id` (`ON DELETE RESTRICT`).
- `audit_log.transaction_id` → `transactions.transaction_id` (`ON DELETE SET NULL`); `audit_log.organization_id` → `organizations.id` (`ON DELETE SET NULL`); `audit_log.actor_user_id` → `users.id` (`ON DELETE SET NULL`).
- `evidence.organization_id`, `seller_tokens.organization_id`, `buyer_tokens.organization_id`, `checkout_links.organization_id` → `organizations.id` (`ON DELETE SET NULL`).

Add these checks:
- `amount_cents >= 0` on `transactions`, `payout_items`, `fake_orders`, and `fake_orders.capture_amount_cents`.
- `debit_cents >= 0`, `credit_cents >= 0`, and `debit_cents + credit_cents > 0` on `ledger_entries`.
- `attempts >= 0` on `provider_operations` and `seller_verifications`-style counters.
- `seq >= 0` on `transaction_events`.
- `status IN ('pending', 'succeeded', 'failed')` on `provider_operations`.
- `currency = upper(currency) AND char_length(currency) = 3` on every currency column.

Add indexes that RLS uses before cutover:
- `ix_transactions_buyer_org` on `transactions(buyer_organization_id)`.
- `ix_transactions_seller_org` on `transactions(seller_organization_id)`.
- keep the existing single-column indexes for every `transaction_id` foreign key.
- `ix_audit_log_org_created` on `audit_log(organization_id, created_at)`.
- `ix_evidence_org_created` on `evidence(organization_id, created_at)`.

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_schema_core.py -q`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/schema.py tests/unit/test_schema_core.py
git commit -m "feat: define core postgres schema metadata"
```

---

### Task 10: Define the tenancy schema metadata

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py`
- Test: `tests/unit/test_schema_tenancy.py`

**Interfaces:**
- Produces tables: `users`, `organizations`, `organization_members`, `platform_admins`, `seller_profiles`, `buyer_profiles`, `organization_invitations`, `seller_onboarding`, `seller_verifications`, `agents`, `agent_credentials`, `agent_test_runs`, `payment_accounts`, `payout_releases`.
- Consumes: core metadata from Task 9 so organization foreign keys resolve.

**UUID conversions**

| Column | New type |
|---|---|
| `users.id` | `UUIDStr` PK |
| `organizations.id` | `UUIDStr` PK |
| `organizations.owner_user_id` | `UUIDStr` FK `users.id` |
| `organization_members.id` | `UUIDStr` PK |
| `organization_members.organization_id` | `UUIDStr` FK `organizations.id` |
| `organization_members.user_id` | `UUIDStr` FK `users.id` |
| `platform_admins.user_id` | `UUIDStr` PK, FK `users.id` |
| `seller_profiles.organization_id`, `buyer_profiles.organization_id` | `UUIDStr`, unique, FK `organizations.id` |
| `organization_invitations.id`, `.organization_id` | `UUIDStr` |
| `seller_onboarding.organization_id` | `UUIDStr` PK, FK `organizations.id` |
| `seller_verifications.id`, `.organization_id` | `UUIDStr` |
| `agents.id`, `.organization_id` | `UUIDStr` |
| `agent_credentials.id`, `.organization_id`, `.agent_id` | `UUIDStr`; `.agent_id` FK `agents.id` |
| `agent_test_runs.id`, `.organization_id`, `.agent_id` | `UUIDStr`; `.agent_id` FK `agents.id` |
| `payment_accounts.id`, `.organization_id` | `UUIDStr` |
| `payout_releases.id`, `.organization_id`, `.transaction_id` | `UUIDStr`; `.transaction_id` FK `transactions.transaction_id` |

**Remaining type changes**
- `seller_onboarding.completed_steps`, `seller_verifications.documents`, `agent_credentials.scopes`, `agent_test_runs.checks` → `JSONB`.
- `seller_verifications.submitted_by`, `.reviewer_user_id`, `agents.created_by`, `platform_admins.granted_by`, `payout_releases.approved_by` stay `TEXT` because they are actor labels, not structural foreign keys.
- all `created_at`, `updated_at`, `verified_at`, `submitted_at`, `completed_at`, `decided_at`, `activated_at`, `revoked_at`, `expires_at` → `UTCDateTime`.
- `agents.policy_drift` stays `String`; `agent_test_runs.passed` becomes `Boolean` and call sites convert `bool(...)`.
- `seller_verifications.status` check: `('pending', 'approved', 'rejected')`.
- `payment_accounts.status` check: `('active', 'disabled')`.
- `organizations.kind` check: `('personal', 'business')`.
- all role strings (`organization_members.role`, invitation role) stay text; do not add an enum check that duplicates `ROLE_PERMISSIONS`.

- [ ] **Step 1: Write the failing tenancy-schema test**

```python
# tests/unit/test_schema_tenancy.py
from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from commerce_core.types import UTCDateTime
from verifund_control_plane import schema


def test_identity_tables_use_uuid_primary_keys() -> None:
    for table, column in (
        (schema.users, "id"),
        (schema.organizations, "id"),
        (schema.organization_members, "id"),
        (schema.organization_invitations, "id"),
        (schema.seller_verifications, "id"),
        (schema.agents, "id"),
        (schema.agent_credentials, "id"),
        (schema.agent_test_runs, "id"),
        (schema.payment_accounts, "id"),
        (schema.payout_releases, "id"),
    ):
        assert isinstance(table.c[column].type, Uuid), table.name
        assert table.c[column].type.as_uuid is False


def test_clerk_and_business_identifiers_stay_text() -> None:
    assert not isinstance(schema.users.c.clerk_user_id.type, Uuid)
    assert not isinstance(schema.organizations.c.clerk_org_id.type, Uuid)
    assert not isinstance(schema.organizations.c.slug.type, Uuid)
    assert not isinstance(schema.seller_profiles.c.seller_id.type, Uuid)
    assert not isinstance(schema.buyer_profiles.c.buyer_id.type, Uuid)


def test_json_and_timestamp_columns() -> None:
    assert isinstance(schema.seller_onboarding.c.completed_steps.type, JSONB)
    assert isinstance(schema.seller_verifications.c.documents.type, JSONB)
    assert isinstance(schema.agent_credentials.c.scopes.type, JSONB)
    assert isinstance(schema.agent_test_runs.c.checks.type, JSONB)
    assert isinstance(schema.seller_verifications.c.created_at.type, UTCDateTime)
    assert isinstance(schema.agent_credentials.c.expires_at.type, UTCDateTime)


def test_organization_foreign_keys_compile() -> None:
    ddl = str(
        CreateTable(schema.seller_profiles).compile(dialect=postgresql.dialect())
    )
    assert "FOREIGN KEY(organization_id) REFERENCES organizations (id)" in ddl
    assert "UNIQUE (organization_id)" in ddl


def test_agent_test_runs_passed_is_boolean() -> None:
    assert str(schema.agent_test_runs.c.passed.type) == "BOOLEAN"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_schema_tenancy.py -q`

Expected: FAIL with `AttributeError: module 'verifund_control_plane.schema' has no attribute 'users'`.

- [ ] **Step 3: Implement the tenancy tables**

Copy the definitions from `tenancy/repository.py::_define_tables`, apply the type table above, and add these constraints:
- `users.clerk_user_id` unique, not null.
- `organizations.clerk_org_id` unique nullable; `organizations.slug` unique nullable.
- `organization_members` unique `(organization_id, user_id)`.
- `seller_profiles.organization_id` and `buyer_profiles.organization_id` unique, not null.
- `seller_onboarding.organization_id` is both PK and FK.
- `platform_admins.user_id` is both PK and FK to `users.id`.
- `payout_releases.transaction_id` FK to `transactions.transaction_id` (`ON DELETE RESTRICT`); `.organization_id` FK to `organizations.id`.
- `agent_credentials.token_hash` unique, not null.
- all organization-scoped tables index `organization_id`.

Exact `users` and `organizations` shapes:

```python
users = Table(
    "users",
    metadata,
    Column("id", UUIDStr, primary_key=True),
    Column("clerk_user_id", String, unique=True, nullable=False),
    Column("email", String),
    Column("name", String),
    Column("status", String, nullable=False, server_default="active"),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
)

organizations = Table(
    "organizations",
    metadata,
    Column("id", UUIDStr, primary_key=True),
    Column("clerk_org_id", String, unique=True),
    Column("kind", String, nullable=False),
    Column("name", String, nullable=False),
    Column("slug", String, unique=True),
    Column("status", String, nullable=False, server_default="active"),
    Column("owner_user_id", UUIDStr, ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    CheckConstraint("kind IN ('personal', 'business')", name="ck_orgs_kind"),
)
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_schema_tenancy.py -q`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/schema.py tests/unit/test_schema_tenancy.py
git commit -m "feat: define tenancy postgres schema metadata"
```

---

### Task 11: Define the agreement schema and the deferrable transaction cycle

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py`
- Test: `tests/unit/test_schema_agreements.py`

**Interfaces:**
- Produces tables: `agreements`, `agreement_versions`, `agreement_decisions`, `agreement_change_requests`, `agreement_approval_tokens`, `agreement_events`.
- Produces the deferred cycle:
  - `transactions.agreement_id` → `agreements.agreement_id`, `use_alter=True`, `deferrable=True`, `initially="DEFERRED"`.
  - `agreements.transaction_id` → `transactions.transaction_id`, `deferrable=True`, `initially="DEFERRED"`.
- Both columns remain `NOT NULL`.

**Type changes**

| Column | New type |
|---|---|
| `agreements.agreement_id` | `UUIDStr` PK |
| `agreements.transaction_id` | `UUIDStr`, unique, deferrable FK |
| `agreements.buyer_organization_id`, `seller_organization_id` | `UUIDStr` nullable, FK `organizations.id` |
| all agreement timestamp columns | `UTCDateTime` |
| `agreements.seller_operator_required` | `Boolean`, `server_default=false()` |
| `agreement_versions.agreement_id` | `UUIDStr`, part of composite PK |
| `agreement_versions.change_request_id` | `UUIDStr` nullable |
| `agreement_versions.created_at`, `superseded_at` | `UTCDateTime` |
| `agreement_decisions.decision_id` | `UUIDStr` PK |
| `agreement_decisions.agreement_id`, `.change_request_id`, `.verified_change_request_id` | `UUIDStr` nullable/not null as in source |
| `agreement_decisions.decided_at` | `UTCDateTime` |
| `agreement_decisions.authority_snapshot` | keep `Text` (opaque document) |
| `agreement_change_requests.change_request_id` | `UUIDStr` PK |
| `agreement_change_requests.agreement_id` | `UUIDStr` FK |
| `agreement_change_requests.created_at`, `resolved_at` | `UTCDateTime` |
| `agreement_change_requests.operations` | keep `Text` |
| `agreement_approval_tokens.jti` | `UUIDStr` PK |
| `agreement_approval_tokens.agreement_id`, `.consumed_by_decision_id` | `UUIDStr` |
| `agreement_approval_tokens.issued_at`, `expires_at`, `used_at`, `revoked_at` | `UTCDateTime` |
| `agreement_events.event_id` | `BigInteger` + `Identity()` autoincrement |
| `agreement_events.agreement_id` | `UUIDStr` FK |
| `agreement_events.payload` | `JSONB` |
| `agreement_events.created_at` | `UTCDateTime` |

`agreement_versions` keeps `PK (agreement_id, version)` and its partial unique index remains a migration concern:
`CREATE UNIQUE INDEX ux_change_pending ON agreement_change_requests(agreement_id) WHERE status = 'PENDING'`.

- [ ] **Step 1: Write the failing agreement-schema test**

```python
# tests/unit/test_schema_agreements.py
from sqlalchemy import BigInteger, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from verifund_control_plane import schema


def test_agreement_uses_uuid_and_timestamptz() -> None:
    assert isinstance(schema.agreements.c.agreement_id.type, Uuid)
    assert isinstance(schema.agreements.c.transaction_id.type, Uuid)
    assert isinstance(schema.agreements.c.created_at.type, type(schema.transactions.c.created_at.type))
    assert isinstance(schema.agreements.c.seller_operator_required.type, postgresql.BOOLEAN)


def test_transaction_agreement_cycle_is_deferrable() -> None:
    transaction_fk = next(
        fk
        for fk in schema.transactions.foreign_keys
        if fk.target_fullname == "agreements.agreement_id"
    )
    agreement_fk = next(
        fk
        for fk in schema.agreements.foreign_keys
        if fk.target_fullname == "transactions.transaction_id"
    )
    assert transaction_fk.deferrable is True
    assert transaction_fk.initially == "DEFERRED"
    assert transaction_fk.use_alter is True
    assert agreement_fk.deferrable is True
    assert agreement_fk.initially == "DEFERRED"


def test_agreement_event_id_is_bigint_identity() -> None:
    column = schema.agreement_events.c.event_id
    assert isinstance(column.type, BigInteger)
    assert column.identity is not None


def test_agreement_child_types() -> None:
    assert isinstance(schema.agreement_versions.c.agreement_id.type, Uuid)
    assert isinstance(schema.agreement_decisions.c.decision_id.type, Uuid)
    assert isinstance(schema.agreement_change_requests.c.change_request_id.type, Uuid)
    assert isinstance(schema.agreement_approval_tokens.c.jti.type, Uuid)
    assert isinstance(schema.agreement_events.c.payload.type, JSONB)
    ddl = str(CreateTable(schema.agreement_events).compile(dialect=postgresql.dialect()))
    assert "BIGSERIAL" in ddl or "GENERATED BY DEFAULT AS IDENTITY" in ddl
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_schema_agreements.py -q`

Expected: FAIL with `AttributeError: module 'verifund_control_plane.schema' has no attribute 'agreements'`.

- [ ] **Step 3: Implement the agreement tables**

Copy `agreements/repository.py::_define_tables`, apply the types above, and add:

```python
from sqlalchemy import BigInteger, Identity

agreements = Table(
    "agreements",
    metadata,
    Column("agreement_id", UUIDStr, primary_key=True),
    Column(
        "transaction_id",
        UUIDStr,
        ForeignKey(
            "transactions.transaction_id",
            name="fk_agreements_transaction",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
        unique=True,
    ),
    # ... remaining columns copied from the existing definition ...
)

agreement_events = Table(
    "agreement_events",
    metadata,
    Column("event_id", BigInteger, Identity(), primary_key=True),
    Column(
        "agreement_id",
        UUIDStr,
        ForeignKey("agreements.agreement_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    # ... remaining columns copied from the existing definition ...
)
```

Add the transaction-side cycle constraint to `transactions`:

```python
    ForeignKeyConstraint(
        ["agreement_id"],
        ["agreements.agreement_id"],
        name="fk_transactions_agreement",
        ondelete="RESTRICT",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    ),
```

Do not add the constraint in two places: `transactions.agreement_id` remains a plain `UUIDStr` column; the `ForeignKeyConstraint` is appended to the table definition.

Add checks:
- `current_version >= 0`, `offer_round >= 0`, `row_version >= 0`.
- `status IN (...)` using `AgreementState` values.
- `agreement_decisions.decision IN ('ACCEPT', 'REJECT', 'REQUEST_CHANGES')`.
- `agreement_change_requests.status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'WITHDRAWN', 'EXPIRED')`.
- `agreement_versions.version >= 0`.
- `agreement_approval_tokens.expires_at >= issued_at`.

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_schema_agreements.py -q`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/schema.py tests/unit/test_schema_agreements.py
git commit -m "feat: define agreement schema and deferrable transaction cycle"
```

---

### Task 12: Create revision `0001_control_plane_schema`

**Files:**
- Create: `apps/verifund_control_plane/migrations/versions/0001_control_plane_schema.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py` (only if autogenerate reveals drift)
- Test: `tests/integration/test_control_plane_migration.py`

**Interfaces:**
- Produces: the complete control-plane schema at revision `0001_control_plane_schema`, including all 39 application tables, the join table, indexes, checks, and the deferrable cycle.
- Consumes: `schema.metadata` from Tasks 9–11.

- [ ] **Step 1: Write the failing migration test**

```python
# tests/integration/test_control_plane_migration.py
import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.support.postgres import (
    ALEMBIC_INI,
    create_test_database,
    drop_test_database,
    upgrade_database,
)


@pytest.fixture
async def scratch_database():
    database = await create_test_database("verifund_control_plane_migration_test")
    try:
        yield database
    finally:
        await drop_test_database(database)


async def test_upgrade_creates_the_complete_schema(scratch_database) -> None:
    await upgrade_database(scratch_database)
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(scratch_database.migrator_url)
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema = 'public'"
                    )
                )
            ).scalars()
        )
        assert "transactions" in tables
        assert "agreements" in tables
        assert "requirement_declaration_submissions" in tables
        assert len(tables) == 40  # 39 application tables + alembic_version

        types = dict(
            (
                await conn.execute(
                    text(
                        "select column_name, data_type from information_schema.columns "
                        "where table_name = 'transactions' "
                        "and column_name in ('transaction_id', 'funding', 'created_at')"
                    )
                )
            ).all()
        )
        assert types["transaction_id"] == "uuid"
        assert types["funding"] == "jsonb"
        assert types["created_at"] == "timestamp with time zone"

        deferred = await conn.scalar(
            text(
                "select confdeferrable and confdeferred from pg_constraint "
                "where conname = 'fk_agreements_transaction'"
            )
        )
        assert deferred is True

        version = await conn.scalar(text("select version_num from alembic_version"))
        assert version == "0001_control_plane_schema"
    await engine.dispose()


async def test_downgrade_removes_application_tables(scratch_database) -> None:
    await upgrade_database(scratch_database)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", scratch_database.migrator_url)
    await asyncio.to_thread(command.downgrade, config, "base")

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(scratch_database.migrator_url)
    async with engine.connect() as conn:
        exists = await conn.scalar(text("select to_regclass('public.transactions')"))
        assert exists is None
    await engine.dispose()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_migration.py -q`

Expected: FAIL — `alembic upgrade head` succeeds with no revisions, then the table assertion fails.

- [ ] **Step 3: Autogenerate the initial revision**

Run:

```bash
cd apps/verifund_control_plane
VERIFUND_DATABASE_URL_UNPOOLED="postgresql+psycopg://cp_migrator@127.0.0.1:55432/verifund_control_plane_test" \
  uv run alembic -c alembic.ini revision --autogenerate \
  --rev-id 0001_control_plane_schema -m "control plane schema"
```

Expected: `Generating .../versions/0001_control_plane_schema_control_plane_schema.py`.

- [ ] **Step 4: Review and correct the generated revision**

Open the generated file and verify:
- `revision = "0001_control_plane_schema"`, `down_revision = None`.
- `op.create_table` exists for all 39 application tables.
- `transactions.agreement_id` is `sa.Uuid()` and the cycle FK is emitted with:
  ```python
  sa.ForeignKeyConstraint(
      ["agreement_id"], ["agreements.agreement_id"],
      name="fk_transactions_agreement",
      ondelete="RESTRICT",
      use_alter=True,
      deferrable=True,
      initially="DEFERRED",
  )
  ```
- `agreements.transaction_id` uses `deferrable=True, initially="DEFERRED"`.
- `requirement_declaration_submissions` exists and `requirement_declarations` has no `submission_ids`.
- JSON columns are `postgresql.JSONB(astext_type=sa.Text())`.
- Timestamp columns are `sa.DateTime(timezone=True)`.
- The partial index is present:
  ```python
  op.create_index(
      "ux_change_pending",
      "agreement_change_requests",
      ["agreement_id"],
      unique=True,
      postgresql_where=sa.text("status = 'PENDING'"),
  )
  ```
- `downgrade()` drops tables in dependency order and drops the partial index.

If autogenerate emits `metadata.create_all` or a SQLite type, fix `schema.py` and regenerate; do not hand-edit around a wrong metadata definition.

- [ ] **Step 5: Re-run the migration tests**

Run: `uv run pytest tests/integration/test_control_plane_migration.py -q`

Expected: PASS, 2 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/migrations/versions/0001_control_plane_schema_control_plane_schema.py apps/verifund_control_plane/verifund_control_plane/schema.py tests/integration/test_control_plane_migration.py
git commit -m "feat: add initial control-plane postgres migration"
```

---

## Milestone 2 — Roles, Grants, and RLS

### Task 13: Provision roles and least-privilege grants

**Files:**
- Create: `scripts/provision_control_plane_roles.py`
- Create: `apps/verifund_control_plane/migrations/versions/0002_roles_grants.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py` (`HEAD_REVISION`)
- Test: `tests/integration/test_control_plane_roles.py`

**Interfaces:**
- Produces roles `cp_migrator`, `cp_app`, `cp_auth`, `cp_service` with:
  - `cp_migrator`: LOGIN, owns schema/tables, no runtime use.
  - `cp_app`: LOGIN, `NOBYPASSRLS`, DML only on tenant tables.
  - `cp_auth`: LOGIN, `BYPASSRLS`, `SELECT` only on `users`, `organizations`, `organization_members`, `platform_admins`.
  - `cp_service`: LOGIN, `BYPASSRLS`, DML on all application tables.
- Produces migration `0002_roles_grants` that verifies roles exist, revokes `PUBLIC`, grants schema/table/sequence privileges, sets role timeouts, and revokes `CONNECT` from `PUBLIC`.
- The migration never creates roles or passwords. `scripts/provision_control_plane_roles.py` does that with the Neon project owner.

- [ ] **Step 1: Write the failing role test**

```python
# tests/integration/test_control_plane_roles.py
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine


async def _scalar(url: str, sql: str):
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        value = await conn.scalar(text(sql))
    await engine.dispose()
    return value


async def test_role_attributes(control_plane_database) -> None:
    bypass = dict(
        (
            await _scalar_all(
                control_plane_database.service_url,
                "select rolname, rolbypassrls from pg_roles "
                "where rolname in ('cp_app', 'cp_auth', 'cp_service')",
            )
        )
    )
    assert bypass == {"cp_app": False, "cp_auth": True, "cp_service": True}


async def _scalar_all(url: str, sql: str):
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).all()
    await engine.dispose()
    return rows


async def test_app_role_can_read_business_tables_but_not_identity_tables(
    control_plane_database,
) -> None:
    assert await _scalar(control_plane_database.app_url, "select count(*) from transactions") == 0
    assert await _scalar(control_plane_database.app_url, "select count(*) from alembic_version") == 1
    with pytest.raises(ProgrammingError, match="permission denied"):
        await _scalar(control_plane_database.app_url, "select count(*) from users")


async def test_app_role_cannot_read_service_only_tables(control_plane_database) -> None:
    for table in ("idempotency_keys", "webhook_events", "reconciler_runs", "fake_orders"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            await _scalar(control_plane_database.app_url, f"select count(*) from {table}")


async def test_auth_role_can_read_identity_tables_but_not_business_tables(
    control_plane_database,
) -> None:
    assert await _scalar(control_plane_database.auth_url, "select count(*) from users") == 0
    assert await _scalar(control_plane_database.auth_url, "select count(*) from organizations") == 0
    with pytest.raises(ProgrammingError, match="permission denied"):
        await _scalar(control_plane_database.auth_url, "select count(*) from transactions")


async def test_service_role_can_read_everything(control_plane_database) -> None:
    for table in ("transactions", "users", "idempotency_keys", "webhook_events"):
        assert await _scalar(control_plane_database.service_url, f"select count(*) from {table}") == 0


async def test_public_cannot_connect_to_the_database(control_plane_database) -> None:
    admin = create_async_engine(control_plane_database.admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text("drop role if exists cp_intruder"))
        await conn.execute(text("create role cp_intruder login"))
    await admin.dispose()

    intruder_url = control_plane_database.admin_url.replace(
        "postgres:postgres@", "cp_intruder@"
    ).replace("/postgres", f"/{control_plane_database.name}")
    engine = create_async_engine(intruder_url)
    with pytest.raises(Exception, match="permission denied|not permitted"):
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    await engine.dispose()

    admin = create_async_engine(control_plane_database.admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text("drop role if exists cp_intruder"))
    await admin.dispose()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_roles.py -q`

Expected: FAIL — `alembic_version` exists but grants are not applied; `cp_app` cannot read `transactions` because no grants exist.

- [ ] **Step 3: Add the provisioning script**

```python
# scripts/provision_control_plane_roles.py
from __future__ import annotations

import argparse
import os

import psycopg
from psycopg import sql

ROLE_ATTRIBUTES = {
    "cp_migrator": "LOGIN",
    "cp_app": "LOGIN NOBYPASSRLS",
    "cp_auth": "LOGIN BYPASSRLS",
    "cp_service": "LOGIN BYPASSRLS",
}


def libpq_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def provision(admin_url: str, database: str) -> None:
    with psycopg.connect(libpq_url(admin_url), autocommit=True) as conn:
        for role, attributes in ROLE_ATTRIBUTES.items():
            conn.execute(
                sql.SQL(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {} ) THEN "
                    "CREATE ROLE {} {}; "
                    "END IF; END $$;"
                ).format(sql.Literal(role), sql.Identifier(role), sql.SQL(attributes))
            )
            password = os.environ.get(f"{role.upper()}_PASSWORD")
            if password:
                conn.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            conn.execute(
                sql.SQL("ALTER ROLE {} {}").format(
                    sql.Identifier(role), sql.SQL(attributes)
                )
            )
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO cp_app, cp_auth, cp_service").format(
                sql.Identifier(database)
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    provision(args.admin_url, args.database)
```

Run it once for a local database with:

```bash
uv run python scripts/provision_control_plane_roles.py \
  --admin-url "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/postgres" \
  --database verifund_control_plane
```

The test harness creates the same roles without passwords because local Compose uses trust auth.

- [ ] **Step 4: Add migration `0002_roles_grants`**

Create `apps/verifund_control_plane/migrations/versions/0002_roles_grants.py`:

```python
"""roles and grants

Revision ID: 0002_roles_grants
Revises: 0001_control_plane_schema
"""
from __future__ import annotations

from alembic import op

revision = "0002_roles_grants"
down_revision = "0001_control_plane_schema"
branch_labels = None
depends_on = None

APP_TABLES = (
    "transactions",
    "transaction_events",
    "ledger_entries",
    "evidence",
    "evidence_submissions",
    "requirement_declarations",
    "requirement_declaration_submissions",
    "provider_operations",
    "payout_items",
    "seller_tokens",
    "buyer_tokens",
    "invitation_tokens",
    "checkout_links",
    "receipts",
    "audit_log",
    "agreements",
    "agreement_versions",
    "agreement_decisions",
    "agreement_change_requests",
    "agreement_approval_tokens",
    "agreement_events",
    "seller_profiles",
    "buyer_profiles",
    "seller_onboarding",
    "seller_verifications",
    "agents",
    "agent_credentials",
    "agent_test_runs",
    "payment_accounts",
    "payout_releases",
    "organization_invitations",
    "organizations",
)

IDENTITY_TABLES = ("users", "organizations", "organization_members", "platform_admins")
SERVICE_ONLY_TABLES = (
    "idempotency_keys",
    "webhook_events",
    "reconciler_runs",
    "fake_orders",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cp_app') THEN
            RAISE EXCEPTION 'cp_app is missing; run scripts/provision_control_plane_roles.py';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cp_auth') THEN
            RAISE EXCEPTION 'cp_auth is missing; run scripts/provision_control_plane_roles.py';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cp_service') THEN
            RAISE EXCEPTION 'cp_service is missing; run scripts/provision_control_plane_roles.py';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cp_migrator') THEN
            RAISE EXCEPTION 'cp_migrator is missing; run scripts/provision_control_plane_roles.py';
          END IF;
        END
        $$;
        """
    )
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO cp_app, cp_auth, cp_service")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(APP_TABLES) + " TO cp_app"
    )
    op.execute("GRANT SELECT ON alembic_version TO cp_app")
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_app, cp_service"
    )
    op.execute("GRANT SELECT ON " + ", ".join(IDENTITY_TABLES) + " TO cp_auth")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cp_service"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_service")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cp_service
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO cp_app, cp_service
        """
    )
    op.execute(
        """
        DO $$
        DECLARE db text := current_database();
        BEGIN
          EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', db);
          EXECUTE format('GRANT CONNECT ON DATABASE %I TO cp_app, cp_auth, cp_service, cp_migrator', db);
        END
        $$;
        """
    )
    for role in ("cp_app", "cp_auth", "cp_service"):
        op.execute(
            f"ALTER ROLE {role} SET statement_timeout = '30s'"
        )
        op.execute(
            f"ALTER ROLE {role} SET lock_timeout = '5s'"
        )
        op.execute(
            f"ALTER ROLE {role} SET idle_in_transaction_session_timeout = '30s'"
        )


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cp_app, cp_auth, cp_service")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM cp_app, cp_auth, cp_service")
    op.execute("REVOKE USAGE ON SCHEMA public FROM cp_app, cp_auth, cp_service")
```

Update `schema.HEAD_REVISION = "0002_roles_grants"`.

- [ ] **Step 5: Re-run the role tests**

Run: `uv run pytest tests/integration/test_control_plane_roles.py -q`

Expected: PASS, 6 tests. The `cp_intruder` role is dropped even when the connection assertion fails, because the test uses a separate admin connection in teardown.

- [ ] **Step 6: Commit**

```bash
git add scripts/provision_control_plane_roles.py apps/verifund_control_plane/migrations/versions/0002_roles_grants.py apps/verifund_control_plane/verifund_control_plane/schema.py tests/integration/test_control_plane_roles.py
git commit -m "feat: provision control-plane roles and grants"
```

---

### Task 14: Add RLS policies and the policy matrix

**Files:**
- Create: `apps/verifund_control_plane/migrations/versions/0003_rls_policies.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/schema.py` (`HEAD_REVISION`)
- Test: `tests/integration/test_control_plane_rls.py`

**Interfaces:**
- Produces forced RLS on the tables named in design §5.3.
- Tenant predicate:
  ```sql
  NULLIF(current_setting('app.tenant_id', true), '')::uuid
  ```
- `cp_service` continues to bypass via role attribute; `cp_auth` bypasses for pre-tenant identity reads but has no business-table grants; `cp_app` is subject to every policy.

- [ ] **Step 1: Write the failing RLS test**

```python
# tests/integration/test_control_plane_rls.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.uow import UnitOfWork

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
ORG_S = "33333333-3333-4333-8333-333333333333"
USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TXN_SHARED = "44444444-4444-4444-8444-444444444444"
TXN_B = "55555555-5555-4555-8555-555555555555"
AGR_SHARED = "66666666-6666-4666-8666-666666666666"
AGR_B = "77777777-7777-4777-8777-777777777777"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


async def seed(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        conn = uow.connection
        await conn.execute(
            schema.users.insert(),
            [
                {"id": USER_A, "clerk_user_id": "clerk-a", "email": "a@example.com",
                 "name": "A", "status": "active", "created_at": NOW, "updated_at": NOW},
                {"id": USER_B, "clerk_user_id": "clerk-b", "email": "b@example.com",
                 "name": "B", "status": "active", "created_at": NOW, "updated_at": NOW},
            ],
        )
        await conn.execute(
            schema.organizations.insert(),
            [
                {"id": ORG_A, "kind": "business", "name": "Buyer A", "slug": "buyer-a",
                 "status": "active", "owner_user_id": USER_A, "created_at": NOW, "updated_at": NOW},
                {"id": ORG_B, "kind": "business", "name": "Buyer B", "slug": "buyer-b",
                 "status": "active", "owner_user_id": USER_B, "created_at": NOW, "updated_at": NOW},
                {"id": ORG_S, "kind": "business", "name": "Seller S", "slug": "seller-s",
                 "status": "active", "owner_user_id": USER_A, "created_at": NOW, "updated_at": NOW},
            ],
        )
        await conn.execute(
            schema.seller_profiles.insert(),
            {"seller_id": "seller-s", "organization_id": ORG_S, "display_name": "Seller S",
             "verification_status": "verified", "created_at": NOW, "updated_at": NOW},
        )
        await conn.execute(
            schema.buyer_profiles.insert(),
            [
                {"buyer_id": "buyer-a", "organization_id": ORG_A, "created_at": NOW},
                {"buyer_id": "buyer-b", "organization_id": ORG_B, "created_at": NOW},
            ],
        )
        common = {
            "run_id": "run-1", "offer_id": "offer-1", "state": "AWARDED",
            "version": 1, "last_seq": 0, "amount_cents": 1000, "currency": "USD",
            "agreement_hash": "a" * 64, "agreement_version": 1, "deadlines": {},
            "created_at": NOW, "updated_at": NOW,
        }
        await conn.execute(
            schema.transactions.insert(),
            [
                {**common, "transaction_id": TXN_SHARED, "buyer_id": "buyer-a",
                 "seller_id": "seller-s", "buyer_organization_id": ORG_A,
                 "seller_organization_id": ORG_S, "agreement_id": AGR_SHARED},
                {**common, "transaction_id": TXN_B, "buyer_id": "buyer-b",
                 "seller_id": "seller-s", "buyer_organization_id": ORG_B,
                 "seller_organization_id": ORG_S, "agreement_id": AGR_B},
            ],
        )
        agreement_common = {
            "run_id": "run-1", "seller_id": "seller-s", "current_version": 1,
            "status": "PENDING_SELLER", "offer_id": "offer-1", "offer_round": 1,
            "offer_hash": "b" * 64, "offer_valid_until": NOW, "row_version": 1,
            "seller_operator_required": False, "created_at": NOW, "updated_at": NOW,
        }
        await conn.execute(
            schema.agreements.insert(),
            [
                {**agreement_common, "agreement_id": AGR_SHARED, "transaction_id": TXN_SHARED,
                 "buyer_id": "buyer-a", "buyer_organization_id": ORG_A,
                 "seller_organization_id": ORG_S},
                {**agreement_common, "agreement_id": AGR_B, "transaction_id": TXN_B,
                 "buyer_id": "buyer-b", "buyer_organization_id": ORG_B,
                 "seller_organization_id": ORG_S},
            ],
        )
        await conn.execute(
            schema.transaction_events.insert(),
            [
                {"transaction_id": TXN_SHARED, "seq": 1, "type": "awarded",
                 "payload": {}, "actor": "system", "created_at": NOW},
                {"transaction_id": TXN_B, "seq": 1, "type": "awarded",
                 "payload": {}, "actor": "system", "created_at": NOW},
            ],
        )
    await engine.dispose()


@pytest.fixture
async def seeded(control_plane_database):
    await seed(control_plane_database)
    return control_plane_database


async def _visible_transactions(database, tenant: str | None):
    engine = create_postgres_engine(database.app_url)
    async with UnitOfWork(engine, tenant_id=tenant) as uow:
        rows = (
            await uow.connection.execute(select(schema.transactions.c.transaction_id))
        ).scalars().all()
    await engine.dispose()
    return set(rows)


async def test_buyer_and_seller_see_the_shared_transaction(seeded) -> None:
    assert await _visible_transactions(seeded, ORG_A) == {TXN_SHARED}
    assert await _visible_transactions(seeded, ORG_S) == {TXN_SHARED, TXN_B}
    assert await _visible_transactions(seeded, ORG_B) == {TXN_B}


async def test_missing_tenant_fails_closed(seeded) -> None:
    assert await _visible_transactions(seeded, None) == set()


async def test_unrelated_organization_sees_nothing(seeded) -> None:
    assert await _visible_transactions(seeded, "99999999-9999-4999-8999-999999999999") == set()


async def test_child_rows_follow_the_parent_transaction(seeded) -> None:
    engine = create_postgres_engine(seeded.app_url)
    async with UnitOfWork(engine, tenant_id=ORG_A) as uow:
        rows = (
            await uow.connection.execute(select(schema.transaction_events.c.transaction_id))
        ).scalars().all()
    await engine.dispose()
    assert rows == [TXN_SHARED]


async def test_with_check_rejects_cross_tenant_writes(seeded) -> None:
    engine = create_postgres_engine(seeded.app_url)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with UnitOfWork(engine, tenant_id=ORG_A) as uow:
            await uow.connection.execute(
                schema.transactions.update()
                .where(schema.transactions.c.transaction_id == TXN_SHARED)
                .values(buyer_organization_id=ORG_B, seller_organization_id=ORG_B)
            )
    await engine.dispose()


async def test_service_role_sees_every_transaction(seeded) -> None:
    engine = create_postgres_engine(seeded.service_url)
    async with UnitOfWork(engine) as uow:
        rows = (
            await uow.connection.execute(select(schema.transactions.c.transaction_id))
        ).scalars().all()
    await engine.dispose()
    assert set(rows) == {TXN_SHARED, TXN_B}


async def test_auth_role_cannot_read_business_tables(seeded) -> None:
    engine = create_postgres_engine(seeded.auth_url)
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with UnitOfWork(engine) as uow:
            await uow.connection.execute(select(schema.transactions.c.transaction_id))
    await engine.dispose()


async def test_tenant_context_does_not_leak_across_pooled_connections(seeded) -> None:
    engine = create_postgres_engine(seeded.app_url, pool_size=1, max_overflow=0)
    async with UnitOfWork(engine, tenant_id=ORG_A) as uow:
        assert len((await uow.connection.execute(select(schema.transactions))).all()) == 1
    async with UnitOfWork(engine) as uow:
        assert (await uow.connection.execute(select(schema.transactions))).all() == []
    await engine.dispose()


async def test_evidence_and_audit_use_org_or_parent(seeded) -> None:
    engine = create_postgres_engine(seeded.service_url)
    async with UnitOfWork(engine) as uow:
        await uow.connection.execute(
            schema.evidence.insert(),
            [
                {"evidence_id": "88888888-8888-4888-8888-888888888888",
                 "transaction_id": TXN_SHARED, "seller_id": "seller-s", "kind": "document",
                 "sha256": "c" * 64, "media_type": "text/plain", "size_bytes": 1,
                 "original_filename": "a.txt", "purpose": "requirement",
                 "created_at": NOW},
                {"evidence_id": "99999999-9999-4999-8999-999999999999",
                 "transaction_id": TXN_B, "seller_id": "seller-s", "kind": "document",
                 "sha256": "d" * 64, "media_type": "text/plain", "size_bytes": 1,
                 "original_filename": "b.txt", "purpose": "requirement",
                 "created_at": NOW},
            ],
        )
    await engine.dispose()

    engine = create_postgres_engine(seeded.app_url)
    async with UnitOfWork(engine, tenant_id=ORG_A) as uow:
        rows = (
            await uow.connection.execute(select(schema.evidence.c.transaction_id))
        ).scalars().all()
    await engine.dispose()
    assert rows == [TXN_SHARED]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_rls.py -q`

Expected: FAIL — all rows are visible because RLS is not enabled, and the auth-role test currently fails on missing grants rather than on policy.

- [ ] **Step 3: Add migration `0003_rls_policies`**

Create `apps/verifund_control_plane/migrations/versions/0003_rls_policies.py`:

```python
"""row-level security policies

Revision ID: 0003_rls_policies
Revises: 0002_roles_grants
"""
from __future__ import annotations

from alembic import op

revision = "0003_rls_policies"
down_revision = "0002_roles_grants"
branch_labels = None
depends_on = None

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
DUAL_ORG_TABLES = ("transactions", "agreements")
SINGLE_ORG_TABLES = (
    "seller_profiles",
    "buyer_profiles",
    "seller_onboarding",
    "seller_verifications",
    "agents",
    "agent_credentials",
    "agent_test_runs",
    "payment_accounts",
    "payout_releases",
    "organization_invitations",
)
AGREEMENT_CHILD_TABLES = (
    "agreement_versions",
    "agreement_decisions",
    "agreement_change_requests",
    "agreement_approval_tokens",
    "agreement_events",
)
TRANSACTION_CHILD_TABLES = (
    "transaction_events",
    "ledger_entries",
    "evidence_submissions",
    "provider_operations",
    "payout_items",
    "receipts",
    "seller_tokens",
    "buyer_tokens",
    "invitation_tokens",
    "checkout_links",
)


def _enable(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _tenant_is(expression: str) -> str:
    return f"({expression} = {TENANT})"


def _parent_exists(child_table: str, parent: str, parent_key: str) -> str:
    if parent == "transactions":
        match = (
            f"t.buyer_organization_id = {TENANT} "
            f"OR t.seller_organization_id = {TENANT}"
        )
    else:
        match = (
            f"a.buyer_organization_id = {TENANT} "
            f"OR a.seller_organization_id = {TENANT}"
        )
    return (
        "EXISTS (SELECT 1 FROM "
        f"{parent} p WHERE p.{parent_key} = {child_table}.{parent_key} "
        f"AND ({match.replace('t.', 'p.').replace('a.', 'p.')}))"
    )


def upgrade() -> None:
    for table in DUAL_ORG_TABLES:
        _enable(table)
        expression = (
            f"buyer_organization_id = {TENANT} "
            f"OR seller_organization_id = {TENANT}"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL TO cp_app "
            f"USING ({expression}) WITH CHECK ({expression})"
        )

    for table in SINGLE_ORG_TABLES:
        _enable(table)
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL TO cp_app "
            f"USING ({_tenant_is('organization_id')}) "
            f"WITH CHECK ({_tenant_is('organization_id')})"
        )

    _enable("organizations")
    op.execute(
        f"CREATE POLICY organizations_tenant ON organizations FOR ALL TO cp_app "
        f"USING (id = {TENANT}) WITH CHECK (id = {TENANT})"
    )

    for table in TRANSACTION_CHILD_TABLES:
        _enable(table)
        exists = _parent_exists(table, "transactions", "transaction_id")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL TO cp_app "
            f"USING ({exists}) WITH CHECK ({exists})"
        )

    _enable("requirement_declaration_submissions")
    declaration_exists = (
        "EXISTS (SELECT 1 FROM requirement_declarations d "
        "JOIN transactions t ON t.transaction_id = d.transaction_id "
        f"WHERE d.declaration_id = requirement_declaration_submissions.declaration_id "
        f"AND (t.buyer_organization_id = {TENANT} "
        f"OR t.seller_organization_id = {TENANT}))"
    )
    op.execute(
        "CREATE POLICY requirement_declaration_submissions_tenant "
        "ON requirement_declaration_submissions FOR ALL TO cp_app "
        f"USING ({declaration_exists}) WITH CHECK ({declaration_exists})"
    )

    for table in AGREEMENT_CHILD_TABLES:
        _enable(table)
        exists = _parent_exists(table, "agreements", "agreement_id")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL TO cp_app "
            f"USING ({exists}) WITH CHECK ({exists})"
        )

    _enable("evidence")
    evidence_policy = (
        f"organization_id = {TENANT} OR "
        + _parent_exists("evidence", "transactions", "transaction_id")
    )
    op.execute(
        "CREATE POLICY evidence_tenant ON evidence FOR ALL TO cp_app "
        f"USING ({evidence_policy}) WITH CHECK ({evidence_policy})"
    )

    _enable("audit_log")
    audit_policy = (
        f"organization_id = {TENANT} OR "
        "transaction_id IS NOT NULL AND "
        + _parent_exists("audit_log", "transactions", "transaction_id")
    )
    op.execute(
        "CREATE POLICY audit_log_tenant ON audit_log FOR ALL TO cp_app "
        f"USING ({audit_policy}) WITH CHECK ({audit_policy})"
    )


def downgrade() -> None:
    tables = (
        *DUAL_ORG_TABLES,
        *SINGLE_ORG_TABLES,
        "organizations",
        *TRANSACTION_CHILD_TABLES,
        "requirement_declaration_submissions",
        *AGREEMENT_CHILD_TABLES,
        "evidence",
        "audit_log",
    )
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
```

The local helper `_parent_exists` must generate the parent alias `p`; verify the emitted SQL before running. If the string replacement is unclear, write each policy explicitly instead of using the helper. The required predicates are exactly the ones in design §5.3.

Update `schema.HEAD_REVISION = "0003_rls_policies"`.

- [ ] **Step 4: Re-run the RLS tests**

Run: `uv run pytest tests/integration/test_control_plane_rls.py -q`

Expected: PASS, 9 tests. If a policy references a missing table, the migration fails; fix `schema.py` before changing the migration.

- [ ] **Step 5: Run the migration and role tests together**

Run:

```bash
uv run pytest tests/integration/test_control_plane_migration.py \
  tests/integration/test_control_plane_roles.py \
  tests/integration/test_control_plane_rls.py -q
```

Expected: PASS. The migration downgrade test now runs through `0003`.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/migrations/versions/0003_rls_policies.py apps/verifund_control_plane/verifund_control_plane/schema.py tests/integration/test_control_plane_rls.py
git commit -m "feat: enforce control-plane row-level security"
```

---

## Milestone 3 — Repository Port

### Task 15: Refactor the core repository onto the bound connection

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_repository.py`, `tests/unit/test_verifund_repository_aux.py`, `tests/unit/test_repository_boundaries.py`

**Interfaces:**
- Produces:
  - `Repository(engine=None)` that reads tables from `schema.metadata`.
  - `Repository._conn(conn)` returning `conn` or `current_uow().connection`.
  - `Repository.transaction()` yields the bound connection without committing.
  - `pg_insert` for `idempotency_keys` and `evidence` conflict handling.
- Removes: `configure_sqlite`, `sqlite_insert`, `create_schema`, `_ensure_column`, every `self.engine.connect()`/`self.engine.begin()`.

- [ ] **Step 1: Write the failing boundary test**

```python
# tests/unit/test_repository_boundaries.py
from pathlib import Path

from sqlalchemy import text

from verifund_control_plane import repository as repository_module
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.repository import Repository
from verifund_control_plane.uow import UnitOfWork, bind_uow, reset_uow


def test_core_repository_has_no_engine_owned_transactions() -> None:
    source = Path(repository_module.__file__).read_text()
    assert "self.engine.connect" not in source
    assert "self.engine.begin" not in source
    assert "sqlite_insert" not in source
    assert "create_schema" not in source


async def test_repository_transaction_is_the_bound_uow(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        token = bind_uow(uow)
        try:
            repo = Repository()
            async with repo.transaction() as conn:
                assert conn is uow.connection
            assert uow.in_transaction is True
        finally:
            reset_uow(token)
    await engine.dispose()


async def test_repository_reads_through_the_uow_connection(control_plane_database, db_conn) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        token = bind_uow(uow)
        try:
            repo = Repository()
            assert await repo.count_transactions() == 0
            await uow.connection.execute(
                text("insert into organizations (id, kind, name, status, created_at, updated_at) "
                     "values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'business', 'A', "
                     "'active', now(), now())")
            )
            assert await repo.get_organization_count() == 1
        finally:
            reset_uow(token)
    await engine.dispose()
```

If `get_organization_count` does not exist, use `Repository` only for transaction counts and move the second assertion into Task 16, where tenancy methods are converted. Do not add a production method only for the test.

- [ ] **Step 2: Run the boundary test and confirm it fails**

Run: `uv run pytest tests/unit/test_repository_boundaries.py -q`

Expected: FAIL on `self.engine.connect` in the source scan.

- [ ] **Step 3: Replace table definitions with schema imports**

At the top of `repository.py`, remove the SQLAlchemy table imports and `sqlite_insert`, then import:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

from verifund_control_plane import schema
from verifund_control_plane.uow import current_uow
```

Replace `__init__` and `_define_tables` with:

```python
class Repository:
    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine
        self.metadata = schema.metadata
        self.transactions = schema.transactions
        self.transaction_events = schema.transaction_events
        self.ledger = schema.ledger_entries
        self.evidence = schema.evidence
        self.evidence_submissions = schema.evidence_submissions
        self.requirement_declarations = schema.requirement_declarations
        self.requirement_declaration_submissions = (
            schema.requirement_declaration_submissions
        )
        self.provider_operations = schema.provider_operations
        self.webhook_events = schema.webhook_events
        self.payout_items = schema.payout_items
        self.idempotency = schema.idempotency_keys
        self.seller_tokens = schema.seller_tokens
        self.buyer_tokens = schema.buyer_tokens
        self.invitation_tokens = schema.invitation_tokens
        self.checkout_links = schema.checkout_links
        self.receipts = schema.receipts
        self.audit_log = schema.audit_log
        self.fake_orders = schema.fake_orders
        self.reconciler_runs = schema.reconciler_runs

    def _conn(self, conn: AsyncConnection | None = None) -> AsyncConnection:
        return conn if conn is not None else current_uow().connection
```

Delete `create_schema()` and `_ensure_column()`.

- [ ] **Step 4: Convert every method mechanically**

For each method, apply exactly one of these patterns:

```python
# Method already accepts a conn argument:
async def get_transaction(self, transaction_id: str, conn: AsyncConnection | None = None):
    conn = self._conn(conn)
    statement = select(self.transactions).where(...)
    row = (await conn.execute(statement)).first()
    ...

# Method does not accept a conn argument:
async def count_transactions(self) -> int:
    conn = self._conn()
    result = await conn.execute(select(self.transactions.c.transaction_id))
    return len(result.all())
```

Then:
- remove every `async with self.engine.connect() as conn:` and `async with self.engine.begin() as conn:` block, dedent its body, and use `conn = self._conn(conn)` where a parameter exists;
- remove every inner `async with self.engine.connect() as own_conn:` fallback in `get_transaction`;
- replace `self.transaction()` with:
  ```python
  @asynccontextmanager
  async def transaction(self) -> AsyncGenerator[AsyncConnection, None]:
      yield current_uow().connection
  ```
- replace `sqlite_insert(self.idempotency)` with `pg_insert(self.idempotency)`;
- replace `sqlite_insert(self.evidence)` with `pg_insert(self.evidence)`.

- [ ] **Step 5: Update declaration persistence**

`add_declaration` keeps its public signature but writes join rows:

```python
async def add_declaration(
    self,
    conn: AsyncConnection | None,
    declaration_id: str,
    transaction_id: str,
    requirement_id: str,
    attempt: int,
    actor: str,
    submission_ids: list[str],
    declared_at: datetime,
) -> None:
    conn = self._conn(conn)
    await conn.execute(
        self.requirement_declarations.insert().values(
            declaration_id=declaration_id,
            transaction_id=transaction_id,
            requirement_id=requirement_id,
            attempt=attempt,
            actor=actor,
            declared_at=declared_at,
        )
    )
    if submission_ids:
        await conn.execute(
            self.requirement_declaration_submissions.insert(),
            [
                {"declaration_id": declaration_id, "submission_id": submission_id}
                for submission_id in submission_ids
            ],
        )
```

`list_declarations` reconstructs `submission_ids` with a `select(...).where(...)` on the join table and keeps the existing dictionary shape.

- [ ] **Step 6: Convert the core repository tests**

Update `tests/unit/test_verifund_repository.py` and `tests/unit/test_verifund_repository_aux.py`:
- remove `tmp_path` SQLite engines and `repo.create_schema()`;
- use the shared `db_conn` fixture for direct connection tests;
- construct `Repository()` (no engine);
- for methods that accept `conn`, pass `db_conn`;
- for methods that rely on `current_uow()`, wrap the calls in `UnitOfWork(engine)` and `bind_uow`.

Run: `uv run pytest tests/unit/test_verifund_repository.py tests/unit/test_verifund_repository_aux.py tests/unit/test_repository_boundaries.py -q`

Expected: PASS. If a test still needs a SQLite URL, it belongs to another service and must not be changed in this task.

- [ ] **Step 7: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py tests/unit/test_verifund_repository.py tests/unit/test_verifund_repository_aux.py tests/unit/test_repository_boundaries.py
git commit -m "refactor: bind core repository to the unit of work"
```

---

### Task 16: Refactor the tenancy repository onto the bound connection

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`
- Test: `tests/unit/test_tenancy_repository.py`, `tests/unit/test_tenant_repository.py`, `tests/unit/test_agent_store.py`, `tests/unit/test_payment_accounts.py`, `tests/unit/test_payout_releases.py`

**Interfaces:**
- Produces `TenancyRepository(engine=None)` with every method accepting an optional connection and defaulting to `current_uow().connection`.
- Removes `configure_sqlite`, `create_schema`, all `self.engine` transactions, and `sqlite_insert`.
- `upsert_user`, `upsert_organization`, `ensure_personal_organization`, and membership upserts perform all their reads and writes on the same connection.

- [ ] **Step 1: Add the failing boundary assertion**

Extend `tests/unit/test_repository_boundaries.py`:

```python
def test_tenancy_repository_has_no_engine_owned_transactions() -> None:
    from verifund_control_plane.tenancy import repository as tenancy_module

    source = Path(tenancy_module.__file__).read_text()
    assert "self.engine.begin" not in source
    assert "self.engine.connect" not in source
    assert "sqlite_insert" not in source
    assert "create_schema" not in source
```

Run: `uv run pytest tests/unit/test_repository_boundaries.py::test_tenancy_repository_has_no_engine_owned_transactions -q`

Expected: FAIL.

- [ ] **Step 2: Import schema tables**

Replace `_define_tables` with:

```python
class TenancyRepository:
    def __init__(self, engine=None) -> None:
        self.engine = engine
        self.metadata = schema.metadata
        self.users = schema.users
        self.organizations = schema.organizations
        self.organization_members = schema.organization_members
        self.platform_admins = schema.platform_admins
        self.seller_profiles = schema.seller_profiles
        self.buyer_profiles = schema.buyer_profiles
        self.organization_invitations = schema.organization_invitations
        self.seller_onboarding = schema.seller_onboarding
        self.seller_verifications = schema.seller_verifications
        self.agents = schema.agents
        self.agent_credentials = schema.agent_credentials
        self.agent_test_runs = schema.agent_test_runs
        self.payment_accounts = schema.payment_accounts
        self.payout_releases = schema.payout_releases

    def _conn(self, conn=None):
        return conn if conn is not None else current_uow().connection
```

Delete `create_schema()` and the `configure_sqlite` import.

- [ ] **Step 3: Convert methods to the same pattern**

Apply the Task 15 pattern to every method. Pay special attention to these methods because they currently nest engine transactions:
- `upsert_user` — read and write on one connection; use `pg_insert(...).on_conflict_do_update(...)` instead of select-then-insert if the existing method races.
- `upsert_organization` — same.
- `ensure_personal_organization` — insert the organization and buyer profile on one connection.
- `upsert_membership_from_clerk` — same.
- `grant_platform_admin` — replace `sqlite_insert` with `pg_insert` and keep `on_conflict_do_nothing`.
- `upsert_seller_onboarding` / `upsert_seller_verification` — same.
- `create_agent`, `create_agent_credential`, `record_agent_test_run`, `create_payment_account`, `create_payout_release` — use `new_uuid()` for generated IDs.

Replace `_id()` with `new_uuid()` and import it from `commerce_core.types`.

- [ ] **Step 4: Convert the tenancy tests**

Update the listed test files:
- replace SQLite engines with `db_conn` or a `UnitOfWork` over `control_plane_database.service_url`;
- remove `await store.create_schema()`;
- pass `conn` where the method accepts it;
- keep assertions about returned dictionaries unchanged unless a type is now native (UUID string, boolean, UTC string).

Run:

```bash
uv run pytest tests/unit/test_tenancy_repository.py tests/unit/test_tenant_repository.py \
  tests/unit/test_agent_store.py tests/unit/test_payment_accounts.py \
  tests/unit/test_payout_releases.py tests/unit/test_repository_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/unit/test_tenancy_repository.py tests/unit/test_tenant_repository.py tests/unit/test_agent_store.py tests/unit/test_payment_accounts.py tests/unit/test_payout_releases.py tests/unit/test_repository_boundaries.py
git commit -m "refactor: bind tenancy repository to the unit of work"
```

---

### Task 17: Refactor the agreement repository and prove the deferred cycle

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/repository.py`
- Test: `tests/unit/test_agreement_repository.py`, `tests/unit/test_agreement_service.py`
- Test: `tests/integration/test_control_plane_deferred_cycle.py`

**Interfaces:**
- Produces `AgreementRepository(engine=None)` with every method connection-bound.
- Removes `create_schema`, the raw partial-index DDL, and the `verifund_control_plane.db.transaction` import.
- Preserves the public repository methods used by `AgreementService`.

- [ ] **Step 1: Write the failing deferred-cycle test**

```python
# tests/integration/test_control_plane_deferred_cycle.py
from datetime import UTC, datetime

from sqlalchemy import select

from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.uow import UnitOfWork

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
ORG = "11111111-1111-4111-8111-111111111111"
TXN = "44444444-4444-4444-8444-444444444444"
AGR = "66666666-6666-4666-8666-666666666666"


async def test_transaction_and_agreement_can_be_inserted_in_one_transaction(
    control_plane_database,
) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        conn = uow.connection
        await conn.execute(
            schema.organizations.insert().values(
                id=ORG, kind="business", name="Org", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        await conn.execute(
            schema.buyer_profiles.insert().values(
                buyer_id="buyer-1", organization_id=ORG, created_at=NOW
            )
        )
        await conn.execute(
            schema.seller_profiles.insert().values(
                seller_id="seller-1", organization_id=ORG, display_name="Seller",
                verification_status="verified", created_at=NOW, updated_at=NOW,
            )
        )
        await conn.execute(
            schema.transactions.insert().values(
                transaction_id=TXN, run_id="run-1", buyer_id="buyer-1",
                seller_id="seller-1", buyer_organization_id=ORG,
                seller_organization_id=ORG, offer_id="offer-1", state="AWARDED",
                version=1, last_seq=0, amount_cents=1000, currency="USD",
                agreement_id=AGR, agreement_hash="a" * 64, agreement_version=1,
                deadlines={}, created_at=NOW, updated_at=NOW,
            )
        )
        await conn.execute(
            schema.agreements.insert().values(
                agreement_id=AGR, transaction_id=TXN, run_id="run-1",
                buyer_id="buyer-1", seller_id="seller-1",
                buyer_organization_id=ORG, seller_organization_id=ORG,
                current_version=1, status="PENDING_SELLER", offer_id="offer-1",
                offer_round=1, offer_hash="b" * 64, offer_valid_until=NOW,
                row_version=1, seller_operator_required=False,
                created_at=NOW, updated_at=NOW,
            )
        )
    async with engine.connect() as conn:
        assert await conn.scalar(
            select(schema.transactions.c.agreement_id).where(
                schema.transactions.c.transaction_id == TXN
            )
        ) == AGR
    await engine.dispose()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_deferred_cycle.py -q`

Expected: FAIL if the repository is still using SQLite transaction helpers or the migration's cycle constraints are missing. If Task 12 already proved the schema, the failure is in the repository import (`verifund_control_plane.db`) or the table metadata.

- [ ] **Step 3: Replace table definitions and conversion methods**

- Import `schema`, `new_uuid`, and `current_uow`; remove `_engine_transaction`, `_json_mod`, and all Table/Column imports.
- In `__init__`, assign `self.metadata = schema.metadata` and each table attribute from `schema`.
- Delete `create_schema()`.
- Convert every method using the Task 15 `_conn` pattern.
- Replace `_id`-style generation in `AgreementService` with `new_uuid()` in Task 18; the repository should accept IDs from the service and never generate them.
- `agreement_events` inserts no longer specify `event_id`; PostgreSQL identity supplies it.
- Keep `terms`, `rendered_html`, `authority_snapshot`, and `operations` as `Text`.
- Keep the `ux_change_pending` partial index in migration `0001` only; remove the runtime DDL.

- [ ] **Step 4: Convert agreement tests**

Update `tests/unit/test_agreement_repository.py` and `tests/unit/test_agreement_service.py`:
- use `db_conn` or a service `UnitOfWork`;
- remove `create_schema`;
- replace prefixed IDs with UUID constants;
- keep assertions on decision/version/state behavior.

Run:

```bash
uv run pytest tests/unit/test_agreement_repository.py tests/unit/test_agreement_service.py \
  tests/integration/test_control_plane_deferred_cycle.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agreements/repository.py tests/unit/test_agreement_repository.py tests/unit/test_agreement_service.py tests/integration/test_control_plane_deferred_cycle.py
git commit -m "refactor: bind agreement repository and prove deferred cycle"
```

---

## Milestone 4 — Identity, Seeding, and Runtime Wiring

### Task 18: Replace prefixed IDs with UUIDs and fix the system principal

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py`
- Test: `tests/unit/test_uuid_ids.py`, `tests/unit/test_system_principal.py`

**Interfaces:**
- Produces:
  - `SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"` in `tenancy/identity.py`.
  - `SYSTEM_IDENTITY.user_id == SYSTEM_USER_ID`, `clerk_user_id == "system"`.
  - Every generated entity ID is `new_uuid()`; no prefix remains.
  - System audit rows use `actor_user_id = NULL` and `actor_type = 'system'` per design §4.5.
- Consumes: `new_uuid` from `commerce_core.types`.

- [ ] **Step 1: Write the failing UUID test**

```python
# tests/unit/test_uuid_ids.py
import re
from pathlib import Path

import pytest

from commerce_core.types import new_uuid
from verifund_control_plane.tenancy.identity import SYSTEM_IDENTITY, SYSTEM_USER_ID


def test_system_principal_uses_a_fixed_uuid() -> None:
    assert SYSTEM_USER_ID == "00000000-0000-0000-0000-000000000001"
    assert SYSTEM_IDENTITY.user_id == SYSTEM_USER_ID
    assert SYSTEM_IDENTITY.clerk_user_id == "system"


def test_new_uuid_returns_a_uuid4_string() -> None:
    value = new_uuid()
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        value,
    )


@pytest.mark.parametrize(
    "module_path",
    [
        "apps/verifund_control_plane/verifund_control_plane/service.py",
        "apps/verifund_control_plane/verifund_control_plane/evidence.py",
        "apps/verifund_control_plane/verifund_control_plane/reconciler.py",
        "apps/verifund_control_plane/verifund_control_plane/repository.py",
        "apps/verifund_control_plane/verifund_control_plane/agreements/service.py",
    ],
)
def test_no_prefixed_entity_id_generation_remains(module_path: str) -> None:
    source = Path(module_path).read_text()
    assert not re.search(
        r"""f["'](vf_|agr_|dec_|cr_|sub_|ev_|op_|le_|aud_|decl_|rec_)""",
        source,
    ), module_path
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_uuid_ids.py -q`

Expected: FAIL — `SYSTEM_USER_ID` does not exist and prefixed generators remain.

- [ ] **Step 3: Replace every generated ID**

Apply these exact replacements:

| File | Old | New |
|---|---|---|
| `service.py` | `f"vf_{uuid.uuid4().hex}"` | `new_uuid()` |
| `service.py` | `f"sub_{uuid.uuid4().hex}"` | `new_uuid()` |
| `service.py` | `f"op_{uuid.uuid4().hex}"` | `new_uuid()` |
| `evidence.py` | `f"ev_{uuid.uuid4().hex}"` | `new_uuid()` |
| `reconciler.py` | `f"rec_{uuid.uuid4().hex}"` | `new_uuid()` |
| `repository.py` | `f"le_{uuid.uuid4().hex}"` | `new_uuid()` |
| `repository.py` | `f"aud_{uuid.uuid4().hex}"` | `new_uuid()` |
| `repository.py` | `f"decl_{uuid.uuid4().hex}"` | `new_uuid()` |
| `agreements/service.py` | `f"agr_{uuid.uuid4().hex}"` | `new_uuid()` |
| `agreements/service.py` | `f"dec_{uuid.uuid4().hex}"` | `new_uuid()` |
| `agreements/service.py` | `f"cr_{uuid.uuid4().hex}"` | `new_uuid()` |

Remove the now-unused `uuid` imports where no other `uuid` symbol is used. Do **not** change:
- `run_id`, `task_id`, `context_id`, `order_id`, PayPal IDs, Clerk IDs, `jti_hash`, `sha256`, `payload_hash`, `idempotency_key`;
- seller/buyer business IDs and organization slugs.

- [ ] **Step 4: Update `SYSTEM_IDENTITY` and system audit handling**

In `tenancy/identity.py`:

```python
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"

SYSTEM_IDENTITY = Identity(
    user_id=SYSTEM_USER_ID,
    clerk_user_id="system",
    tenant_id="",
    clerk_org_id=None,
    role="system",
    permissions=frozenset({"*"}),
    is_platform_admin=True,
    organization_status="active",
)
```

In `Repository.audit`, change the system branch:

```python
        if audit.actor in {"system", "reconciler"}:
            scope = "system"
            actor_type = "system"
            actor_user_id = None
            row = (
                await conn.execute(
                    select(self.transactions).where(
                        self.transactions.c.transaction_id == transaction_id
                    )
                )
            ).first()
            if row is not None:
                organization_id = row.seller_organization_id
```

Update `tests/unit/test_system_principal.py`:
- assert `SYSTEM_IDENTITY.user_id == SYSTEM_USER_ID`;
- assert system audit rows have `actor_user_id is None` and `actor_type == "system"`;
- keep the assertion that system audit rows carry a non-null `organization_id` when the transaction has a seller organization.

- [ ] **Step 5: Re-run the UUID and system tests**

Run:

```bash
uv run pytest tests/unit/test_uuid_ids.py tests/unit/test_system_principal.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/evidence.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/agreements/service.py apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py tests/unit/test_uuid_ids.py tests/unit/test_system_principal.py
git commit -m "feat: use native uuid ids and a fixed system principal"
```

---

### Task 19: Replace the tenancy backfill with an idempotent PostgreSQL seed

**Files:**
- Create: `scripts/seed_control_plane.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py` (remove backfill call in Task 22)
- Test: `tests/integration/test_seed_control_plane.py`

**Interfaces:**
- Produces `seed_control_plane(database_url: str) -> None` and a CLI:
  ```bash
  uv run python scripts/seed_control_plane.py --database-url "$VERIFUND_SERVICE_DATABASE_URL"
  ```
- Seeds:
  - the fixed system user `00000000-0000-0000-0000-000000000001` with `clerk_user_id='system'`;
  - demo buyer organization and `buyer_profiles.buyer_id='demo-buyer'`;
  - four seller organizations and profiles: `northwind-audio`, `circuitforge`, `aurora-supply`, `summit-tech`;
  - one PayPal payout `payment_accounts` row per seller (`provider_account_id` `<seller_id>@example.test`) so `resolve_payout_account` succeeds out of the box;
  - no transactions, events, tokens, or checkpoints.
- Idempotent by deterministic UUIDs and `ON CONFLICT DO NOTHING` / `DO UPDATE` on natural keys.

- [ ] **Step 1: Write the failing seed test**

```python
# tests/integration/test_seed_control_plane.py
from sqlalchemy import func, select

from scripts.seed_control_plane import seed_control_plane
from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.tenancy.identity import SYSTEM_USER_ID


async def _count(engine, table) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(table))


async def test_seed_is_idempotent(control_plane_database, clean_control_plane) -> None:
    await seed_control_plane(control_plane_database.service_url)
    await seed_control_plane(control_plane_database.service_url)
    engine = create_postgres_engine(control_plane_database.service_url)
    try:
        assert await _count(engine, schema.organizations) == 5
        assert await _count(engine, schema.seller_profiles) == 4
        assert await _count(engine, schema.buyer_profiles) == 1
        assert await _count(engine, schema.payment_accounts) == 4
        assert await _count(engine, schema.transactions) == 0
        async with engine.connect() as conn:
            system = (
                await conn.execute(
                    select(schema.users).where(schema.users.c.id == SYSTEM_USER_ID)
                )
            ).first()
        assert system is not None
        assert system.clerk_user_id == "system"
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_seed_control_plane.py -q`

Expected: FAIL with `ModuleNotFoundError: scripts.seed_control_plane`.

- [ ] **Step 3: Implement the seed**

```python
# scripts/seed_control_plane.py
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from commerce_core.types import new_uuid
from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.tenancy.identity import SYSTEM_USER_ID
from verifund_control_plane.uow import UnitOfWork

BUYER_ORG = "10000000-0000-4000-8000-000000000001"
BUYER_PROFILE = "demo-buyer"
SELLERS = (
    ("northwind-audio", "Northwind Audio", "10000000-0000-4000-8000-000000000002"),
    ("circuitforge", "CircuitForge", "10000000-0000-4000-8000-000000000003"),
    ("aurora-supply", "Aurora Supply", "10000000-0000-4000-8000-000000000004"),
    ("summit-tech", "Summit Tech", "10000000-0000-4000-8000-000000000005"),
)


async def seed_control_plane(database_url: str) -> None:
    now = datetime.now(UTC)
    engine = create_postgres_engine(database_url)
    try:
        async with UnitOfWork(engine) as uow:
            conn = uow.connection
            await conn.execute(
                pg_insert(schema.users)
                .values(
                    id=SYSTEM_USER_ID,
                    clerk_user_id="system",
                    email=None,
                    name="Verifund System",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await conn.execute(
                pg_insert(schema.organizations)
                .values(
                    id=BUYER_ORG,
                    kind="business",
                    name="Demo Buyer",
                    slug="demo-buyer",
                    status="active",
                    owner_user_id=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await conn.execute(
                pg_insert(schema.buyer_profiles)
                .values(
                    buyer_id=BUYER_PROFILE,
                    organization_id=BUYER_ORG,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["buyer_id"])
            )
            for seller_id, display_name, organization_id in SELLERS:
                await conn.execute(
                    pg_insert(schema.organizations)
                    .values(
                        id=organization_id,
                        kind="business",
                        name=display_name,
                        slug=seller_id,
                        status="active",
                        owner_user_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
                await conn.execute(
                    pg_insert(schema.seller_profiles)
                    .values(
                        seller_id=seller_id,
                        organization_id=organization_id,
                        display_name=display_name,
                        verification_status="verified",
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["seller_id"])
                )
            for seller_id, _, organization_id in SELLERS:
                existing = await conn.scalar(
                    select(func.count())
                    .select_from(schema.payment_accounts)
                    .where(
                        schema.payment_accounts.c.organization_id == organization_id,
                        schema.payment_accounts.c.provider == "paypal",
                        schema.payment_accounts.c.account_type == "payout",
                    )
                )
                if existing:
                    continue
                await conn.execute(
                    schema.payment_accounts.insert().values(
                        id=new_uuid(),
                        organization_id=organization_id,
                        provider="paypal",
                        provider_account_id=f"{seller_id}@example.test",
                        account_type="payout",
                        status="active",
                        credentials_reference=f"secret:{seller_id}",
                        created_at=now,
                        updated_at=now,
                    )
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    asyncio.run(seed_control_plane(args.database_url))
```

- [ ] **Step 4: Re-run the seed test**

Run: `uv run pytest tests/integration/test_seed_control_plane.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_control_plane.py tests/integration/test_seed_control_plane.py
git commit -m "feat: seed the control plane from postgres"
```

### Task 20: Split identity reads from bootstrap writes

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/tenancy/identity_service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py`
- Modify: `tests/support/postgres.py` (add a settings helper)
- Test: `tests/integration/test_identity_service_postgres.py`
- Test: `tests/unit/test_tenancy_lazy_sync.py`

**Interfaces:**
- Produces `IdentityService(*, auth_engine, service_engine)` with the tenancy methods used by `resolve_identity`:
  - `get_user_by_clerk_id`, `upsert_user`;
  - `get_organization_by_clerk_id`, `upsert_organization`;
  - `get_membership`, `upsert_membership_from_clerk`;
  - `ensure_personal_organization`, `is_platform_admin`.
- Reads open a short `UnitOfWork(auth_engine)` and call the tenancy repository with `conn=uow.connection`.
- Writes open a short `UnitOfWork(service_engine)` and commit before returning.
- Produces `control_plane_settings(database, **overrides)` in `tests/support/postgres.py`, which fills all four required URLs.
- `resolve_identity(store, ...)` keeps its orchestration contract; an `IdentityService` is a drop-in `store`.

- [ ] **Step 1: Add the settings helper and write the failing identity test**

Add to `tests/support/postgres.py`:

```python
def control_plane_settings(database: TestDatabase, **overrides):
    from verifund_control_plane.settings import Settings

    return Settings(
        _env_file=None,
        mode="fake",
        database_url=database.app_url,
        auth_database_url=database.auth_url,
        service_database_url=database.service_url,
        database_url_unpooled=database.migrator_url,
        evidence_dir=overrides.pop("evidence_dir", Path("/tmp/verifund-evidence")),
        reconciler_enabled=False,
        public_base_url="http://test",
        **overrides,
    )
```

```python
# tests/integration/test_identity_service_postgres.py
import pytest
from sqlalchemy import select

from tests.support.postgres import control_plane_settings
from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.tenancy.identity import resolve_identity
from verifund_control_plane.tenancy.identity_service import IdentityService
from verifund_control_plane.uow import UnitOfWork


@pytest.fixture
async def identity_service(control_plane_database, clean_control_plane):
    auth_engine = create_postgres_engine(control_plane_database.auth_url)
    service_engine = create_postgres_engine(control_plane_database.service_url)
    service = IdentityService(
        auth_engine=auth_engine, service_engine=service_engine
    )
    yield service
    await auth_engine.dispose()
    await service_engine.dispose()


async def test_user_bootstrap_writes_through_the_service_role(identity_service):
    user = await identity_service.upsert_user(
        "clerk-new", "new@example.com", "New User"
    )
    assert user["clerk_user_id"] == "clerk-new"

    org = await identity_service.ensure_personal_organization(user["id"])
    assert org["kind"] == "personal"
    assert org["owner_user_id"] == user["id"]

    # The auth role can read both rows after the service role committed them.
    async with UnitOfWork(identity_service.auth_engine) as uow:
        assert await uow.connection.scalar(
            select(schema.users.c.clerk_user_id).where(
                schema.users.c.clerk_user_id == "clerk-new"
            )
        ) == "clerk-new"
        assert await uow.connection.scalar(
            select(schema.organizations.c.id).where(
                schema.organizations.c.id == org["id"]
            )
        ) == org["id"]


async def test_resolve_identity_bootstraps_a_personal_tenant(
    identity_service, control_plane_database
):
    settings = control_plane_settings(control_plane_database)
    identity = await resolve_identity(
        identity_service, {"sub": "clerk-lazy"}, settings, directory=None
    )
    assert identity.clerk_user_id == "clerk-lazy"
    assert identity.tenant_id
    assert identity.role == "org:buyer"

    # A second resolve reuses the committed bootstrap.
    again = await resolve_identity(
        identity_service, {"sub": "clerk-lazy"}, settings, directory=None
    )
    assert again.user_id == identity.user_id
    assert again.tenant_id == identity.tenant_id


async def test_resolve_identity_loads_an_existing_org_and_membership(
    identity_service, control_plane_database
):
    user = await identity_service.upsert_user("clerk-a", "a@example.com", "A")
    org = await identity_service.upsert_organization("org_clerk_a", "Acme", "acme")
    await identity_service.upsert_membership(
        org["id"], user["id"], "org:admin", "mem_a"
    )

    identity = await resolve_identity(
        identity_service,
        {"sub": "clerk-a", "org_id": "org_clerk_a"},
        control_plane_settings(control_plane_database),
        directory=None,
    )
    assert identity.user_id == user["id"]
    assert identity.tenant_id == org["id"]
    assert identity.role == "org:admin"


async def test_identity_service_uses_distinct_role_engines(identity_service):
    assert identity_service.auth_engine.url.username == "cp_auth"
    assert identity_service.service_engine.url.username == "cp_service"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_identity_service_postgres.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane.tenancy.identity_service'`.

- [ ] **Step 3: Implement `IdentityService`**

```python
# apps/verifund_control_plane/verifund_control_plane/tenancy/identity_service.py
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from verifund_control_plane.tenancy.repository import TenancyRepository
from verifund_control_plane.uow import UnitOfWork


class IdentityService:
    """Identity reads use cp_auth; lazy bootstrap writes use cp_service.

    Every method opens one short unit of work, so the former lazy-sync path
    never mixes a read-only role with a write.
    """

    def __init__(self, *, auth_engine: AsyncEngine, service_engine: AsyncEngine) -> None:
        self.auth_engine = auth_engine
        self.service_engine = service_engine
        self._auth = TenancyRepository()
        self._service = TenancyRepository()

    async def _read(self, method: str, *args: Any) -> Any:
        async with UnitOfWork(self.auth_engine) as uow:
            return await getattr(self._auth, method)(*args, conn=uow.connection)

    async def _write(self, method: str, *args: Any) -> Any:
        async with UnitOfWork(self.service_engine) as uow:
            return await getattr(self._service, method)(*args, conn=uow.connection)

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> dict | None:
        return await self._read("get_user_by_clerk_id", clerk_user_id)

    async def upsert_user(
        self, clerk_user_id: str, email: str | None, name: str | None
    ) -> dict:
        return await self._write("upsert_user", clerk_user_id, email, name)

    async def get_organization_by_clerk_id(
        self, clerk_org_id: str
    ) -> dict | None:
        return await self._read("get_organization_by_clerk_id", clerk_org_id)

    async def upsert_organization(
        self, clerk_org_id: str, name: str, slug: str | None
    ) -> dict:
        return await self._write("upsert_organization", clerk_org_id, name, slug)

    async def get_membership(
        self, organization_id: str, user_id: str
    ) -> dict | None:
        return await self._read("get_membership", organization_id, user_id)

    async def upsert_membership(
        self,
        organization_id: str,
        user_id: str,
        role: str,
        clerk_membership_id: str | None = None,
    ) -> dict:
        return await self._write(
            "upsert_membership",
            organization_id,
            user_id,
            role,
            clerk_membership_id,
        )

    async def upsert_membership_from_clerk(self, data: dict) -> dict | None:
        return await self._write("upsert_membership_from_clerk", data)

    async def ensure_personal_organization(self, user_id: str) -> dict:
        return await self._write("ensure_personal_organization", user_id)

    async def is_platform_admin(self, user_id: str) -> bool:
        return await self._read("is_platform_admin", user_id)
```

- [ ] **Step 4: Document the identity seam**

Add a module docstring to `tenancy/identity.py`:

```python
"""Clerk identity resolution.

Reads are served by `IdentityService` through cp_auth. Any missing local
user or organization is created by `IdentityService` through a short cp_service
unit of work. `resolve_identity` itself performs no SQL.
"""
```

Do not change `resolve_identity`'s arguments or its branching. Task 22 swaps the
object on `app.state` from the tenancy repository to `IdentityService`.

- [ ] **Step 5: Convert the lazy-sync unit test**

Replace the SQLite fixture in `tests/unit/test_tenancy_lazy_sync.py` with the
PostgreSQL identity service:

```python
@pytest.fixture
async def store_and_settings(control_plane_database, clean_control_plane):
    auth_engine = create_postgres_engine(control_plane_database.auth_url)
    service_engine = create_postgres_engine(control_plane_database.service_url)
    service = IdentityService(
        auth_engine=auth_engine, service_engine=service_engine
    )
    yield service, control_plane_settings(control_plane_database)
    await auth_engine.dispose()
    await service_engine.dispose()
```

Then replace direct `store.get_organization_by_clerk_id(...)` assertions with
reads through a short auth `UnitOfWork`:

```python
async with UnitOfWork(store.auth_engine) as uow:
    assert await uow.connection.scalar(
        select(schema.organizations.c.id).where(
            schema.organizations.c.clerk_org_id == "org_new"
        )
    ) is not None
```

- [ ] **Step 6: Run the identity tests**

Run:

```bash
uv run pytest tests/integration/test_identity_service_postgres.py \
  tests/unit/test_tenancy_lazy_sync.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/identity_service.py apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py tests/support/postgres.py tests/integration/test_identity_service_postgres.py tests/unit/test_tenancy_lazy_sync.py
git commit -m "feat: split identity reads from bootstrap writes"
```

---

### Task 21: Add route classification, request scope, and token tenant binding

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/middleware.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/routes.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/checkout.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/fulfillment.py`
- Test: `tests/unit/test_route_classification.py`
- Test: `tests/integration/test_request_scope_postgres.py`

**Interfaces:**
- Produces:
  - `RouteClass` (`none`, `service`, `deferred`) and `classify_path(path) -> RouteClass`.
  - `RequestScope` with `uow`, `enter()`, `commit()`, `rollback()`, `close()`.
  - `RequestUnitOfWorkMiddleware` — a pure ASGI middleware that buffers the
    response, opens a `cp_service` UoW for `service` routes, and commits
    before the first response byte, or rolls back on a handler error or any
    `>= 400` response.
  - `tenant_id_for_transaction(service_engine, transaction_id, *, side)` and `tenant_id_for_seller(service_engine, seller_id)`.
  - `enter_transaction_uow(request, transaction_id, *, side)` and `enter_seller_uow(request, seller_id)`.
- Classification rules:
  - `/health`, `/ready`, `/metrics` → `none`;
  - `/ops/sellers/...` → `deferred` (Clerk platform admin);
    `/ops/transactions/.../payout-release` → `deferred`; `/ops/transactions` and
    `/ops/transactions/{id}` stay `service` (ops token);
  - `/v1/webhooks/...` and `/v1/agent-credentials/verify` → `service`;
  - other `/v1/...` → `deferred` (Clerk identity);
  - `/buyer`, `/seller`, `/checkout`, `/return`, `/cancel`, `/fulfillment` → `deferred` (capability token);
  - `/agreements`, `/awards`, `/transactions`, `/ops`, `/webhooks`, `/reconciler` → `service`.
- The middleware commits before the response leaves the app and rolls back on
  any exception or error status. It never holds a transaction for `/health`.
  A FastAPI yield dependency is not used because it unwinds after the response
  is sent; committing there would let a client see a success it may not get.

- [ ] **Step 1: Write the failing classifier and scope tests**

```python
# tests/unit/test_route_classification.py
import pytest

from verifund_control_plane.middleware import RouteClass, classify_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", RouteClass.NONE),
        ("/ready", RouteClass.NONE),
        ("/metrics", RouteClass.NONE),
        ("/awards", RouteClass.SERVICE),
        ("/transactions/vf-1/state", RouteClass.SERVICE),
        ("/transactions/vf-1/fund", RouteClass.SERVICE),
        ("/ops/transactions", RouteClass.SERVICE),
        ("/ops/transactions/vf-1", RouteClass.SERVICE),
        ("/ops/transactions/vf-1/payout-release", RouteClass.DEFERRED),
        ("/ops/sellers/seller-1/verification", RouteClass.DEFERRED),
        ("/webhooks/paypal", RouteClass.SERVICE),
        ("/v1/webhooks/clerk", RouteClass.SERVICE),
        ("/v1/agent-credentials/verify", RouteClass.SERVICE),
        ("/reconciler/run", RouteClass.SERVICE),
        ("/agreements/agr-1", RouteClass.SERVICE),
        ("/buyer/transactions/vf-1/accept", RouteClass.DEFERRED),
        ("/seller/transactions", RouteClass.DEFERRED),
        ("/checkout/fake/token", RouteClass.DEFERRED),
        ("/return/token", RouteClass.DEFERRED),
        ("/cancel/token", RouteClass.DEFERRED),
        ("/fulfillment/access/token", RouteClass.DEFERRED),
        ("/v1/me", RouteClass.DEFERRED),
        ("/v1/seller/onboarding", RouteClass.DEFERRED),
        ("/v1/agents/agent-1/test", RouteClass.DEFERRED),
        ("/unknown", RouteClass.NONE),
    ],
)
def test_route_classification(path: str, expected: RouteClass) -> None:
    assert classify_path(path) is expected
```

```python
# tests/integration/test_request_scope_postgres.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from verifund_control_plane import schema
from verifund_control_plane.middleware import (
    RequestScope,
    tenant_id_for_seller,
    tenant_id_for_transaction,
)
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.uow import UnitOfWork, current_uow

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_S = "33333333-3333-4333-8333-333333333333"
TXN = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


async def _seed_transaction(service_url: str) -> None:
    engine = create_postgres_engine(service_url)
    async with UnitOfWork(engine) as uow:
        conn = uow.connection
        await conn.execute(
            schema.organizations.insert(),
            [
                {"id": ORG_A, "kind": "business", "name": "A", "slug": "a",
                 "status": "active", "created_at": NOW, "updated_at": NOW},
                {"id": ORG_S, "kind": "business", "name": "S", "slug": "s",
                 "status": "active", "created_at": NOW, "updated_at": NOW},
            ],
        )
        await conn.execute(
            schema.seller_profiles.insert().values(
                seller_id="seller-s", organization_id=ORG_S,
                display_name="S", verification_status="verified",
                created_at=NOW, updated_at=NOW,
            )
        )
        await conn.execute(
            schema.transactions.insert().values(
                transaction_id=TXN, run_id="run-1", buyer_id="buyer-a",
                seller_id="seller-s", buyer_organization_id=ORG_A,
                seller_organization_id=ORG_S, offer_id="offer-1",
                state="AWARDED", version=1, last_seq=0, amount_cents=1000,
                currency="USD", agreement_hash="a" * 64, agreement_version=1,
                deadlines={}, created_at=NOW, updated_at=NOW,
            )
        )
    await engine.dispose()


async def test_request_scope_commits_and_resets_the_context(
    control_plane_database, clean_control_plane
) -> None:
    engine = create_postgres_engine(control_plane_database.app_url)
    scope = RequestScope()
    try:
        uow = await scope.enter(engine, tenant_id=ORG_A)
        await uow.connection.execute(
            schema.organizations.insert().values(
                id=ORG_A, kind="business", name="A", slug="a", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        await scope.commit()
        assert uow.in_transaction is False
    finally:
        await scope.close()
    with pytest.raises(RuntimeError, match="no active unit of work"):
        current_uow()

    probe = create_postgres_engine(control_plane_database.service_url)
    async with probe.connect() as conn:
        assert await conn.scalar(
            select(schema.organizations.c.id).where(schema.organizations.c.id == ORG_A)
        ) == ORG_A
    await probe.dispose()
    await engine.dispose()


async def test_request_scope_rolls_back(
    control_plane_database, clean_control_plane
) -> None:
    engine = create_postgres_engine(control_plane_database.app_url)
    scope = RequestScope()
    try:
        uow = await scope.enter(engine, tenant_id=ORG_A)
        await uow.connection.execute(
            schema.organizations.insert().values(
                id=ORG_A, kind="business", name="A", slug="a", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        await scope.rollback()
    finally:
        await scope.close()

    probe = create_postgres_engine(control_plane_database.service_url)
    async with probe.connect() as conn:
        assert await conn.scalar(text("select count(*) from organizations")) == 0
    await probe.dispose()
    await engine.dispose()


async def test_transaction_and_seller_tenant_lookup(
    control_plane_database, clean_control_plane
) -> None:
    await _seed_transaction(control_plane_database.service_url)
    lookup = create_postgres_engine(control_plane_database.service_url)
    try:
        assert await tenant_id_for_transaction(
            lookup, TXN, side="buyer"
        ) == ORG_A
        assert await tenant_id_for_transaction(
            lookup, TXN, side="seller"
        ) == ORG_S
        assert await tenant_id_for_seller(lookup, "seller-s") == ORG_S
    finally:
        await lookup.dispose()


async def test_middleware_commits_before_the_first_byte(
    control_plane_database, clean_control_plane
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import func

    from verifund_control_plane.middleware import RequestUnitOfWorkMiddleware

    engine = create_postgres_engine(control_plane_database.service_url)

    async def downstream(scope, receive, send):
        uow = current_uow()
        await uow.connection.execute(
            schema.organizations.insert().values(
                id=ORG_A, kind="business", name="A", slug="a", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    app = RequestUnitOfWorkMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/awards",
        "app": SimpleNamespace(
            state=SimpleNamespace(service_engine=engine)
        ),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    try:
        await app(scope, receive, send)
    finally:
        await engine.dispose()
    assert sent[0]["status"] == 201
    probe = create_postgres_engine(control_plane_database.service_url)
    async with probe.connect() as conn:
        assert await conn.scalar(
            select(func.count()).select_from(schema.organizations)
        ) == 1
    await probe.dispose()


async def test_middleware_rolls_back_error_responses(
    control_plane_database, clean_control_plane
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import func

    from verifund_control_plane.middleware import RequestUnitOfWorkMiddleware

    engine = create_postgres_engine(control_plane_database.service_url)

    async def downstream(scope, receive, send):
        uow = current_uow()
        await uow.connection.execute(
            schema.organizations.insert().values(
                id=ORG_A, kind="business", name="A", slug="a", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        await send({"type": "http.response.start", "status": 409, "headers": []})
        await send({"type": "http.response.body", "body": b"no"})

    app = RequestUnitOfWorkMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/awards",
        "app": SimpleNamespace(
            state=SimpleNamespace(service_engine=engine)
        ),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    try:
        await app(scope, receive, send)
    finally:
        await engine.dispose()
    assert sent[0]["status"] == 409
    probe = create_postgres_engine(control_plane_database.service_url)
    async with probe.connect() as conn:
        assert await conn.scalar(
            select(func.count()).select_from(schema.organizations)
        ) == 0
    await probe.dispose()


async def test_middleware_rolls_back_handler_exceptions(
    control_plane_database, clean_control_plane
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import func

    from verifund_control_plane.middleware import RequestUnitOfWorkMiddleware

    engine = create_postgres_engine(control_plane_database.service_url)

    async def downstream(scope, receive, send):
        uow = current_uow()
        await uow.connection.execute(
            schema.organizations.insert().values(
                id=ORG_A, kind="business", name="A", slug="a", status="active",
                created_at=NOW, updated_at=NOW,
            )
        )
        raise RuntimeError("boom")

    app = RequestUnitOfWorkMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/awards",
        "app": SimpleNamespace(
            state=SimpleNamespace(service_engine=engine)
        ),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):  # pragma: no cover - handler raises first
        raise AssertionError("response must not be sent")

    with pytest.raises(RuntimeError, match="boom"):
        await app(scope, receive, send)
    await engine.dispose()
    probe = create_postgres_engine(control_plane_database.service_url)
    async with probe.connect() as conn:
        assert await conn.scalar(
            select(func.count()).select_from(schema.organizations)
        ) == 0
    await probe.dispose()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
uv run pytest tests/unit/test_route_classification.py \
  tests/integration/test_request_scope_postgres.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane.middleware'`.

- [ ] **Step 3: Implement the classifier and request scope**

```python
# apps/verifund_control_plane/verifund_control_plane/middleware.py
from __future__ import annotations

from collections.abc import MutableMapping
from contextvars import Token
from enum import StrEnum
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp

from verifund_control_plane import schema
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.uow import UnitOfWork, bind_uow, reset_uow


class RouteClass(StrEnum):
    NONE = "none"
    SERVICE = "service"
    DEFERRED = "deferred"


_SERVICE_PREFIXES = (
    "/awards",
    "/transactions",
    "/ops",
    "/webhooks",
    "/reconciler",
    "/agreements",
)
_DEFERRED_PREFIXES = (
    "/buyer",
    "/seller",
    "/checkout",
    "/return",
    "/cancel",
    "/fulfillment",
)
_NONE_PATHS = {"/health", "/ready", "/metrics"}


def classify_path(path: str) -> RouteClass:
    if path in _NONE_PATHS:
        return RouteClass.NONE
    # Clerk-authenticated platform endpoints sit below /ops but run with
    # cp_service only after identity and platform-admin checks. Everything
    # else below /ops is the ops-token router and stays service-scoped.
    if path.startswith("/ops/sellers/"):
        return RouteClass.DEFERRED
    if path.startswith("/ops/transactions/") and path.endswith("/payout-release"):
        return RouteClass.DEFERRED
    if path.startswith("/v1/webhooks/") or path == "/v1/agent-credentials/verify":
        return RouteClass.SERVICE
    if path.startswith("/v1/"):
        return RouteClass.DEFERRED
    if path.startswith(_DEFERRED_PREFIXES):
        return RouteClass.DEFERRED
    if path.startswith(_SERVICE_PREFIXES):
        return RouteClass.SERVICE
    return RouteClass.NONE


class RequestScope:
    """One unit of work for one HTTP request.

    `service` routes enter it before the handler. Capability-token routes enter
    a tenant-scoped UoW after the token and transaction have been resolved.
    """

    def __init__(self) -> None:
        self._uow: UnitOfWork | None = None
        self._token: Token[UnitOfWork | None] | None = None

    @property
    def uow(self) -> UnitOfWork | None:
        return self._uow

    async def enter(
        self,
        engine: AsyncEngine,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> UnitOfWork:
        if self._uow is not None:
            raise RuntimeError("a unit of work is already active for this request")
        uow = UnitOfWork(engine, tenant_id=tenant_id, user_id=user_id)
        await uow.__aenter__()
        self._uow = uow
        self._token = bind_uow(uow)
        return uow

    async def commit(self) -> None:
        if self._uow is not None and self._uow.in_transaction:
            await self._uow.commit()

    async def rollback(self) -> None:
        if self._uow is not None and self._uow.in_transaction:
            await self._uow.rollback()

    async def close(self) -> None:
        if self._token is not None:
            reset_uow(self._token)
            self._token = None
        if self._uow is not None:
            await self._uow.__aexit__(None, None, None)
            self._uow = None


class RequestUnitOfWorkMiddleware:
    """One unit of work per HTTP request.

    Buffers the response so the transaction commits before the first byte
    leaves the app. Any exception from the handler rolls the transaction
    back; so does any `>= 400` response. `service` routes open a `cp_service`
    unit of work up front; capability-token routes open a tenant-scoped UoW
    from inside the handler; everything else runs without a transaction.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        route_scope = RequestScope()
        scope.setdefault("state", {})
        scope["state"]["uow_scope"] = route_scope
        if classify_path(scope["path"]) is RouteClass.SERVICE:
            await route_scope.enter(scope["app"].state.service_engine)
        messages: list[MutableMapping[str, Any]] = []

        async def capture(message) -> None:
            messages.append(message)

        try:
            await self.app(scope, receive, capture)
        except BaseException:
            await route_scope.rollback()
            await route_scope.close()
            raise
        status = _response_status(messages)
        if status >= 400:
            await route_scope.rollback()
        else:
            await route_scope.commit()
        await route_scope.close()
        for message in messages:
            await send(message)


def _response_status(messages) -> int:
    for message in messages:
        if message["type"] == "http.response.start":
            return int(message["status"])
    return 500


async def tenant_id_for_transaction(
    service_engine: AsyncEngine, transaction_id: str, *, side: str
) -> str:
    column = (
        schema.transactions.c.buyer_organization_id
        if side == "buyer"
        else schema.transactions.c.seller_organization_id
    )
    async with UnitOfWork(service_engine) as uow:
        tenant_id = await uow.connection.scalar(
            select(column).where(
                schema.transactions.c.transaction_id == transaction_id
            )
        )
    if tenant_id is None:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return str(tenant_id)


async def tenant_id_for_seller(service_engine: AsyncEngine, seller_id: str) -> str:
    async with UnitOfWork(service_engine) as uow:
        tenant_id = await uow.connection.scalar(
            select(schema.seller_profiles.c.organization_id).where(
                schema.seller_profiles.c.seller_id == seller_id
            )
        )
    if tenant_id is None:
        raise VerifundError("not_found", "seller not found", status_code=404)
    return str(tenant_id)


async def enter_transaction_uow(
    request: Request, transaction_id: str, *, side: str
) -> UnitOfWork:
    scope: RequestScope = request.state.uow_scope
    if scope.uow is not None:
        return scope.uow
    tenant_id = await tenant_id_for_transaction(
        request.app.state.service_engine, transaction_id, side=side
    )
    return await scope.enter(request.app.state.engine, tenant_id=tenant_id)


async def enter_seller_uow(request: Request, seller_id: str) -> UnitOfWork:
    scope: RequestScope = request.state.uow_scope
    if scope.uow is not None:
        return scope.uow
    tenant_id = await tenant_id_for_seller(
        request.app.state.service_engine, seller_id
    )
    return await scope.enter(request.app.state.engine, tenant_id=tenant_id)
```

- [ ] **Step 4: Bind identity and platform-admin requests**

In `tenancy/identity.py`, split resolution from binding:

```python
async def resolve_request_identity(request: Request) -> Identity:
    authenticator = getattr(request.app.state, "clerk_authenticator", None)
    payload = (
        authenticator(request)
        if authenticator is not None
        else _default_authenticator(request, request.app.state.settings)
    )
    return await resolve_identity(
        request.app.state.identity_service, payload, request.app.state.settings
    )


async def require_identity(request: Request) -> Identity:
    from verifund_control_plane.middleware import enter_identity_uow

    identity = await resolve_request_identity(request)
    await enter_identity_uow(request, identity)
    return identity
```

Add to `middleware.py`:

```python
async def enter_identity_uow(request: Request, identity) -> UnitOfWork:
    scope: RequestScope = request.state.uow_scope
    if scope.uow is not None:
        return scope.uow
    return await scope.enter(
        request.app.state.engine,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
    )


async def enter_service_uow(request: Request) -> UnitOfWork:
    scope: RequestScope = request.state.uow_scope
    if scope.uow is not None:
        return scope.uow
    return await scope.enter(request.app.state.service_engine)
```

In `tenancy/routes.py`:

```python
async def require_platform_admin(request: Request) -> Identity:
    provided = request.headers.get("authorization", "")
    if provided.startswith("Bearer ") and secrets.compare_digest(
        provided.removeprefix("Bearer "), request.app.state.settings.ops_token
    ):
        identity = SYSTEM_IDENTITY
    else:
        identity = await resolve_request_identity(request)
        if not identity.is_platform_admin:
            raise VerifundError(
                "forbidden", "platform admin required", status_code=403
            )
    await enter_service_uow(request)
    return identity
```

Import `resolve_request_identity` and `enter_service_uow`. Remove the now-unused
`require_identity` import if no other handler uses it.

- [ ] **Step 5: Bind capability-token routes after verification**

`api/buyer.py` — after `claims = ...verify(...)`:

```python
from verifund_control_plane.middleware import enter_transaction_uow

await enter_transaction_uow(request, transaction_id, side="buyer")
```

Then read the stored token and transaction. The RLS tenant is now the buyer
organization.

`api/seller.py` — in `authenticate`, after verifying the signature and the
`claims.txn == transaction_id` check:

```python
await enter_transaction_uow(request, transaction_id, side="seller")
```

In `authenticate_seller`, after verifying the token:

```python
await enter_seller_uow(request, claims.seller_id)
```

`api/checkout.py` — in all four handlers, after `_claims(...)`:

```python
await enter_transaction_uow(request, claims.transaction_id, side="buyer")
```

`api/fulfillment.py` — verify the invitation token before entering the UoW:

```python
claims = request.app.state.invitation_tokens.verify(
    token, required_scope="txn:read"
)
await enter_transaction_uow(request, claims.txn, side="seller")
return await _service(request).exchange_invitation(token)
```

Do not add token parsing to the classifier; the classifier only chooses whether
the request starts with a service UoW or waits for a capability check.

- [ ] **Step 6: Re-run the scope tests**

Run:

```bash
uv run pytest tests/unit/test_route_classification.py \
  tests/integration/test_request_scope_postgres.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/middleware.py apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py apps/verifund_control_plane/verifund_control_plane/tenancy/routes.py apps/verifund_control_plane/verifund_control_plane/api/buyer.py apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/api/checkout.py apps/verifund_control_plane/verifund_control_plane/api/fulfillment.py tests/unit/test_route_classification.py tests/integration/test_request_scope_postgres.py
git commit -m "feat: bind request-scoped units of work by route class"
```

---

## Milestone 5 — App Wiring, Provider Boundaries, and Test Port

### Task 22: Wire the control plane app onto PostgreSQL

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/health.py`
- Modify: `tests/conftest.py` (shared app fixtures)
- Test: `tests/integration/test_control_plane_app_postgres.py`

**Interfaces:**
- `create_app` builds three engines with `create_postgres_engine`:
  `engine` (`cp_app`), `auth_engine` (`cp_auth`), `service_engine` (`cp_service`),
  passing `db_pool_size`, `db_max_overflow`, `db_pool_timeout`, `db_pool_recycle`.
- `app.state.engine`, `app.state.auth_engine`, `app.state.service_engine`,
  `app.state.identity_service`, `app.state.tenancy` (a `TenancyRepository`).
- `Repository()`, `TenancyRepository()`, `AgreementRepository()` constructed
  without an engine.
- `RequestUnitOfWorkMiddleware` installed with `app.add_middleware`.
- Startup fail-fast: `assert_schema_revision` on a short `NullPool` engine
  over `database_url_unpooled`; the app refuses to boot on an unmigrated
  database.
- `/metrics` opens a short service-role unit of work scoped to the request.
- Lifespan no longer calls `configure_sqlite`, `create_schema()`, or the
  tenancy backfill; seeding is a deploy step (`scripts/seed_control_plane.py`).
- Shared pytest fixtures: `control_plane_app` (runs the lifespan against a
  clean migrated database) and `control_plane_client`.

- [ ] **Step 1: Extend `tests/conftest.py` with the app fixtures**

Append to `tests/conftest.py`:

```python
import httpx
import pytest

from tests.support.award_flow import NOW
from tests.support.postgres import control_plane_settings
from verifund_control_plane.app import create_app


@pytest.fixture
async def control_plane_app(control_plane_database, clean_control_plane, tmp_path):
    settings = control_plane_settings(
        control_plane_database, evidence_dir=tmp_path / "evidence"
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def control_plane_client(control_plane_app):
    transport = httpx.ASGITransport(app=control_plane_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
```

- [ ] **Step 2: Write the failing app test**

```python
# tests/integration/test_control_plane_app_postgres.py
async def test_app_boots_against_postgres_and_serves_ready(
    control_plane_client, control_plane_app
) -> None:
    app = control_plane_app
    assert app.state.engine.url.username == "cp_app"
    assert app.state.auth_engine.url.username == "cp_auth"
    assert app.state.service_engine.url.username == "cp_service"
    assert app.state.identity_service.service_engine is app.state.service_engine

    ready = await control_plane_client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    metrics = await control_plane_client.get("/metrics")
    assert metrics.status_code == 200
    assert "verifund_transactions 0" in metrics.text
```

- [ ] **Step 3: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_app_postgres.py -q`

Expected: FAIL — `create_app` still builds a SQLite engine or `configure_sqlite`
raises on the PostgreSQL connection string.

- [ ] **Step 4: Rewrite `app.py` to construct PostgreSQL engines**

Replace the imports of `db` and the engine construction. The top of `create_app`
becomes:

```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from verifund_control_plane.middleware import RequestUnitOfWorkMiddleware
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.schema import assert_schema_revision
from verifund_control_plane.tenancy.identity_service import IdentityService
from verifund_control_plane.uow import UnitOfWork
```

Remove `from verifund_control_plane.db import configure_sqlite, create_engine`.

```python
    settings = settings or Settings()
    settings.validate_for_mode()
    if getattr(settings, "_clerk_directory", None) is None:
        from verifund_control_plane.tenancy.clerk import ClerkBackendDirectory

        settings._clerk_directory = ClerkBackendDirectory(  # type: ignore[attr-defined]
            settings.clerk_secret_key
        )
    now = clock or (lambda: datetime.now(UTC))
    pool = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }
    app_engine = create_postgres_engine(
        settings.database_url, application_name="verifund-control-plane", **pool
    )
    auth_engine = create_postgres_engine(
        settings.auth_database_url,
        application_name="verifund-control-plane-auth",
        pool_size=2,
        max_overflow=0,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=pool["pool_recycle"],
    )
    service_engine = create_postgres_engine(
        settings.service_database_url,
        application_name="verifund-control-plane-service",
        **pool,
    )
    repo = Repository()
    tenancy = TenancyRepository()
    agreement_repo = AgreementRepository()
    identity_service = IdentityService(
        auth_engine=auth_engine, service_engine=service_engine
    )
```

Keep the rest of the wiring (tokens, links, evidence, receipts, fake or sandbox
payments, tracking, service, reconciler construction) exactly as it is.

Replace the `lifespan` function with:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        revision_engine = create_async_engine(
            settings.database_url_unpooled, poolclass=NullPool
        )
        async with revision_engine.connect() as conn:
            await assert_schema_revision(conn)
        await revision_engine.dispose()
        if (
            hasattr(app.state, "reconciler")
            and settings.mode != "off"
            and settings.reconciler_enabled
        ):
            app.state.reconciler.start()
        try:
            yield
        finally:
            if hasattr(app.state, "reconciler"):
                await app.state.reconciler.stop()
            await auth_engine.dispose()
            await service_engine.dispose()
            await app_engine.dispose()
```

Then update app construction and state:

```python
    app = FastAPI(title="Verifund Control Plane", lifespan=lifespan)
    app.add_middleware(RequestUnitOfWorkMiddleware)
    app.state.settings = settings
    app.state.engine = app_engine
    app.state.auth_engine = auth_engine
    app.state.service_engine = service_engine
    app.state.clock = now
    app.state.repo = repo
    app.state.tenancy = tenancy
    app.state.identity_service = identity_service
    app.state.agreement_repo = agreement_repo
```

(Keep every other `app.state.*` assignment unchanged.)

- [ ] **Step 5: Point `/metrics` at a short service-role unit of work**

Replace `health.py` with:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text

from verifund_control_plane import schema
from verifund_control_plane.uow import UnitOfWork

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "verifund-control-plane"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready", "service": "verifund-control-plane"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    engine = request.app.state.service_engine
    async with UnitOfWork(engine) as uow:
        count = await uow.connection.scalar(
            select(func.count()).select_from(schema.transactions)
        )
    return (
        "# HELP verifund_transactions Number of transactions.\n"
        "# TYPE verifund_transactions gauge\n"
        f"verifund_transactions {count}\n"
    )
```

- [ ] **Step 6: Run the app test**

Run: `uv run pytest tests/integration/test_control_plane_app_postgres.py -q`

Expected: PASS. Tests that still build SQLite apps or call
`Settings(database_url=sqlite...)` fail from this point until Task 25 converts
them; that is expected and is swept up in Task 25.

- [ ] **Step 7: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/app.py apps/verifund_control_plane/verifund_control_plane/api/health.py tests/conftest.py tests/integration/test_control_plane_app_postgres.py
git commit -m "feat: wire the control plane app onto postgres"
```

---

### Task 23: Isolate provider HTTP calls behind commit/call/commit boundaries

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/uow.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/paypal/fake.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/checkout.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Modify: `tests/unit/test_unit_of_work.py`
- Modify: `tests/unit/test_verifund_fake_payments.py`
- Create: `tests/integration/test_verifund_provider_boundaries.py`

**Interfaces:**
- Produces `provider_boundary()` in `uow.py`: commits the bound unit of work,
  runs the enclosed provider call with no open transaction, then begins a
  fresh transaction so the caller can record the outcome. The body must not
  execute SQL.
- Produces `checkpoint()` in `uow.py`: commits the bound unit of work and
  immediately begins a new one, for handlers that persist state before
  returning an error response.
- `FakePaymentPort(repo, service_engine, *, scenario, clock)` performs every
  fake read/write in a dedicated service-role unit of work; it never uses the
  request transaction.
- `resolve_payout_account(store, organization_id, *, conn=None)` and
  `resolve_payout_account_for_seller(store, seller_id, *, conn=None)` bind to
  the current unit of work or an explicit connection; the engine `.connect()`
  shortcut is removed.
- `_payout_email` propagates `payout_account_unavailable` instead of silently
  falling back when tenancy is enabled.
- Handlers keep persistence and provider calls separate. Failures persisted
  before returning an error go through `checkpoint()`.
- Checkout cancel passes `idempotency_key=None`; cancel is state-idempotent,
  and capability-token routes cannot write `idempotency_keys`.

- [ ] **Step 1: Add failing boundary tests to `test_unit_of_work.py`**

```python
async def test_provider_boundary_commits_then_reopens(
    control_plane_database, clean_control_plane
) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    try:
        async with UnitOfWork(engine) as uow:
            await uow.connection.execute(
                schema.organizations.insert().values(
                    id=ORG_A, kind="business", name="A", slug="a",
                    status="active", created_at=NOW, updated_at=NOW,
                )
            )
            async with provider_boundary():
                assert uow.in_transaction is False
            assert uow.in_transaction is True
        probe = create_postgres_engine(control_plane_database.service_url)
        async with probe.connect() as conn:
            assert await conn.scalar(
                select(schema.organizations.c.id).where(
                    schema.organizations.c.id == ORG_A
                )
            ) == ORG_A
        await probe.dispose()
    finally:
        await engine.dispose()


async def test_checkpoint_commits_and_reopens(
    control_plane_database, clean_control_plane
) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    try:
        async with UnitOfWork(engine) as uow:
            await uow.connection.execute(
                schema.organizations.insert().values(
                    id=ORG_A, kind="business", name="A", slug="a",
                    status="active", created_at=NOW, updated_at=NOW,
                )
            )
            await checkpoint()
            assert uow.in_transaction is True
        probe = create_postgres_engine(control_plane_database.service_url)
        async with probe.connect() as conn:
            assert await conn.scalar(
                select(schema.organizations.c.id).where(
                    schema.organizations.c.id == ORG_A
                )
            ) == ORG_A
        await probe.dispose()
    finally:
        await engine.dispose()
```

The test file needs `from verifund_control_plane.uow import checkpoint, provider_boundary, UnitOfWork`, the `schema` import, `ORG_A` and `NOW` constants, and uses the shared fixtures from Task 3.

- [ ] **Step 2: Confirm they fail**

Run: `uv run pytest tests/unit/test_unit_of_work.py -q`

Expected: FAIL with `ImportError: cannot import name 'checkpoint'`.

- [ ] **Step 3: Implement `provider_boundary` and `checkpoint`**

Append to `uow.py`:

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


@asynccontextmanager
async def provider_boundary() -> AsyncGenerator[None, None]:
    """Commit the bound unit of work, call the provider, re-open it.

    The transaction is committed before the provider HTTP call runs, so no
    PayPal request ever overlaps an open database transaction. A fresh
    transaction (with the same tenant context) is begun afterwards so the
    caller can record the outcome. The body may not execute SQL.
    """
    uow = current_uow()
    await uow.commit()
    try:
        yield
    finally:
        await uow.begin()


async def checkpoint() -> None:
    """Commit the bound unit of work and immediately begin a new one.

    Use in handlers that intentionally persist state before returning an
    error response (provider failure records, webhook events).
    """
    uow = current_uow()
    await uow.commit()
    await uow.begin()
```

- [ ] **Step 4: Confirm the boundary tests pass**

Run: `uv run pytest tests/unit/test_unit_of_work.py -q`

Expected: PASS.

- [ ] **Step 5: Refactor payout-account resolution onto the unit of work**

In `tenancy/repository.py`, replace `resolve_payout_account` with:

```python
async def resolve_payout_account(store, organization_id: str, *, conn=None) -> dict:
    from verifund_control_plane.errors import VerifundError

    conn = store._conn(conn)
    rows = (
        await conn.execute(
            select(store.payment_accounts).where(
                store.payment_accounts.c.organization_id == organization_id,
                store.payment_accounts.c.provider == "paypal",
                store.payment_accounts.c.account_type == "payout",
                store.payment_accounts.c.status == "active",
            )
        )
    ).all()
    accounts = [dict(r._mapping) for r in rows]
    if len(accounts) != 1:
        raise VerifundError(
            "payout_account_unavailable",
            "payout account unavailable",
            status_code=409,
        )
    return accounts[0]


async def resolve_payout_account_for_seller(store, seller_id: str, *, conn=None) -> dict:
    profile = await store.get_seller_profile(seller_id, conn)
    if profile is None:
        from verifund_control_plane.errors import VerifundError

        raise VerifundError(
            "payout_account_unavailable",
            "payout account unavailable",
            status_code=409,
        )
    return await resolve_payout_account(store, profile["organization_id"], conn=conn)
```

- [ ] **Step 6: Give `FakePaymentPort` its own service-role unit of work**

Change the constructor signature to `FakePaymentPort(repo, service_engine, *, scenario="success", clock=None)`. In every method that reads or writes `fake_orders`, replace `async with self.repo.transaction() as conn:` and bare `self.repo.get_*` calls with:

```python
async with UnitOfWork(self.service_engine) as uow:
    ...
```

passing `uow.connection` to the repository, for example:

```python
    async def create_order(self, txn, *, return_url, cancel_url, idempotency_key) -> OrderResult:
        ...
        async with UnitOfWork(self.service_engine) as uow:
            await self.repo.save_fake_order(
                uow.connection,
                order_id=order_id,
                transaction_id=txn.transaction_id,
                status="CREATED",
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                payer_action_url=return_url,
                raw={"id": order_id, "status": "CREATED"},
            )
```

`capture_order` performs a read, the scenario branch, then an update — do them in one `UnitOfWork` so the read-modify-write is atomic. Convert `get_order`, `get_payout_item`, `upsert_payout_item` handling the same way and pass `conn` into `repo.get_fake_order`, `repo.update_fake_order`, `repo.save_fake_order`, `repo.upsert_payout_item`. Import `UnitOfWork` from `verifund_control_plane.uow`.

Update `app.py` to pass it:

```python
        payments = FakePaymentPort(
            repo,
            service_engine,
            scenario=settings.fake_payment_scenario,
            clock=now,
        )
```

Convert `tests/unit/test_verifund_fake_payments.py`: construct the port with
`create_postgres_engine(control_plane_database.service_url)`, keep
`clean_control_plane` truncation per test, and read back `fake_orders` through a
short `UnitOfWork(service_engine)` with `bind_uow` for the repository calls,
as in Task 15.

- [ ] **Step 7: Route provider calls through the boundary**

In `service.py`, import the boundary helpers:

```python
from verifund_control_plane.uow import checkpoint, current_uow, provider_boundary
```

`checkpoint` is unused today; `current_uow` is used for the `fund()` failure
path. Apply exactly these edits:

1. `fund()` — wrap only the provider call:
   ```python
        try:
            async with provider_boundary():
                order = await self.payments.create_order(
                    record,
                    return_url=provider_return,
                    cancel_url=provider_cancel,
                    idempotency_key=order_key,
                )
        except VerifundError as exc:
            async with self.repo.transaction() as conn:
                ...   # unchanged: mark FUNDING_PENDING/create_failed
            await self.repo.update_provider_operation(
                operation_id, status="failed", last_error=exc.message,
                increment_attempts=True,
            )
            await checkpoint()
            raise
   ```
   The `checkpoint()` before `raise` is required: the persisted failure record
   is part of the intentional contract, and unhandled handler exceptions must
   still roll back staged-but-unintended writes.
2. `refresh_funding()` — wrap `payments.get_order(...)` and the conditional
   `payments.capture_order(...)` in one `provider_boundary()` block.
3. `_execute_payout()` — wrap `self.payments.create_payout(...)` in a
   `provider_boundary()` block.
4. `retry_payout()` — wrap `self.payments.get_payout_item(...)` in a
   `provider_boundary()` block.
5. `refresh_payout()` — wrap `self.payments.get_payout_item(...)` in a
   `provider_boundary()` block.
6. `recover_operation()` — wrap `self.payments.create_order(...)` in a
   `provider_boundary()` block.
7. `register_tracker()` — wrap `self.tracking.sync(...)` in a
   `provider_boundary()` block.
8. `refresh_tracker()` — wrap `self.tracking.fetch(...)` in a
   `provider_boundary()` block.

No provider HTTP call may remain outside a boundary, and no boundary body may
contain SQL.

- [ ] **Step 8: Drop the idempotency key from checkout cancel**

In `api/checkout.py`:

```python
        if action == "cancel":
            await service.cancel(
                record.transaction_id,
                CancelRequest(
                    reason_code=CancelReason.BUYER_CANCELLED,
                    note="fake checkout canceled",
                ),
                actor="fake-checkout",
                idempotency_key=None,
            )
```

and the matching `idempotency_key=f"cancel:{claims.transaction_id}:paypal"` in
`paypal_cancel` becomes `idempotency_key=None`. Cancel is idempotent on state;
capability routes may not write `idempotency_keys`.

In `checkout_action`, wrap the fake capture call:

```python
        if action == "approve":
            order_id = (record.funding or {}).get("provider_order_id")
            if not order_id:
                raise VerifundError(
                    "provider_unavailable",
                    "funding order is not ready",
                    status_code=503,
                )
            async with provider_boundary():
                capture = await request.app.state.payments.capture_order(
                    str(order_id), idempotency_key=f"capture:{record.transaction_id}:v1"
                )
            await service.apply_capture(
                record.transaction_id, capture, actor="fake-checkout"
            )
```

importing `provider_boundary` from `verifund_control_plane.uow`.

- [ ] **Step 9: `_payout_email` propagates the account error**

```python
    async def _payout_email(self, seller_id: str) -> str | None:
        if getattr(self.settings, "tenancy_enabled", False) and self.tenancy is not None:
            from verifund_control_plane.tenancy.repository import (
                resolve_payout_account_for_seller,
            )

            account = await resolve_payout_account_for_seller(self.tenancy, seller_id)
            return account["provider_account_id"]
        return self.settings.payout_email_for(seller_id)
```

The broad `except Exception: return None` is removed; a missing payout account
is a 409 `payout_account_unavailable`, and reconciliation surfaces it instead
of paying a `seller-id@example.test` address.

- [ ] **Step 10: Write the boundary integration tests**

```python
# tests/integration/test_verifund_provider_boundaries.py
from sqlalchemy import text

from tests.support.award_flow import OPS, approve, award
from verifund_control_plane.pg import create_postgres_engine


async def test_pending_operation_is_committed_before_the_provider_call(
    control_plane_client, control_plane_app, control_plane_database, monkeypatch
) -> None:
    body = await award(control_plane_client)
    txn = body["transaction_id"]
    await approve(control_plane_client, body)

    observed: dict[str, int] = {}
    app = control_plane_app
    original = app.state.payments.create_order

    async def spy(*args, **kwargs):
        engine = create_postgres_engine(control_plane_database.service_url)
        async with engine.connect() as conn:
            observed["started"] = int(
                await conn.scalar(
                    text(
                        "select count(*) from provider_operations "
                        "where transaction_id = :txn"
                    ),
                    {"txn": txn},
                )
            )
        await engine.dispose()
        return await original(*args, **kwargs)

    monkeypatch.setattr(app.state.payments, "create_order", spy)
    resp = await control_plane_client.post(
        f"/transactions/{txn}/fund",
        json={
            "agreement_hash": body["agreement_hash"],
            "agreement_version": body["agreement_version"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txn}:spy"},
    )
    assert resp.status_code == 200, resp.text
    assert observed["started"] == 1


async def test_fund_failure_persists_the_failure_record(
    control_plane_client, control_plane_app, monkeypatch
) -> None:
    from verifund_control_plane.errors import VerifundError

    body = await award(control_plane_client)
    txn = body["transaction_id"]
    await approve(control_plane_client, body)

    async def failing(*args, **kwargs):
        raise VerifundError(
            "provider_unavailable", "fake down", status_code=503, retryable=True
        )

    monkeypatch.setattr(control_plane_app.state.payments, "create_order", failing)
    resp = await control_plane_client.post(
        f"/transactions/{txn}/fund",
        json={
            "agreement_hash": body["agreement_hash"],
            "agreement_version": body["agreement_version"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txn}:fail"},
    )
    assert resp.status_code == 503
    state = (
        await control_plane_client.get(
            f"/transactions/{txn}/state", headers=OPS
        )
    ).json()
    assert state["state"] == "FUNDING_PENDING"
    assert state["funding"]["status"] == "create_failed"


Note: `award` and `approve` set the funding inputs; `approve` uses the ops
token and the award body. `OPS` and the helper signatures are already used by
`tests/support/award_flow.py`.

- [ ] **Step 11: Run the boundary and provider suites**

Run:

```bash
uv run pytest tests/unit/test_unit_of_work.py tests/unit/test_verifund_fake_payments.py -q
uv run pytest tests/integration/test_verifund_provider_boundaries.py -q
```

Expected: PASS. Existing app-level tests in the `/checkout` area fail until
Task 25.

- [ ] **Step 12: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/uow.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py apps/verifund_control_plane/verifund_control_plane/paypal/fake.py apps/verifund_control_plane/verifund_control_plane/api/checkout.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_unit_of_work.py tests/unit/test_verifund_fake_payments.py tests/integration/test_verifund_provider_boundaries.py
git commit -m "feat: isolate provider calls behind commit/call/commit boundaries"
```

---

### Task 24: Give webhooks and the reconciler their own unit-of-work phases

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/webhooks.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Create: `tests/integration/test_reconciler_unit_of_work.py`
- Modify: `tests/integration/test_verifund_provider_boundaries.py` (webhook boundary test)

**Interfaces:**
- `/webhooks/paypal`:
  1. `provider_boundary()` around PayPal signature verification — verification
     HTTP runs with no open transaction;
  2. the event insert commits via `checkpoint()` before dispatch, so the
     event row survives a downstream failure;
  3. on a dispatch error, `mark_webhook_event(..., "failed", ...)` then
     `checkpoint()`, so partial capture application rolls nothing that must
     persist; PayPal redelivery re-applies captures idempotently (the
     `capture_id` check in `apply_capture` is the idempotency key).
- `/v1/webhooks/clerk`:
  1. no provider call; `apply_clerk_event` writes in the request UoW and
     commits at the end of the request; on any error the middleware rolls
     back, which is correct for an atomic "verify → record → apply" step.
- `Reconciler` gains `service_engine` and runs each candidate in its own
  short service-role unit of work. `run_once` reads candidate lists in short
  UoWs and processes each record in a fresh UoW. The final
  `reconciler_runs` row is written in its own UoW.
- **Deviation from design §6.3 (SKIP LOCKED):** the deployed topology is a
  single reconciler process, and every sweep that calls PayPal must release
  its transaction at `provider_boundary()`, so `SELECT ... FOR UPDATE SKIP
  LOCKED` cannot hold a claim across a provider call. Candidate reads and
  per-item UoWs plus the optimistic `version`/`last_seq` checks and
  `provider_operations` idempotency give effectively-once processing instead.
  If the reconciler ever runs as multiple workers, add a real claim column
  and re-evaluate. Flag this at review; do not silently treat it as the
  general answer.

- [ ] **Step 1: Rewrite `paypal_webhook`**

Replace the handler body with:

```python
@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    raw = await request.body()
    if settings.is_fake:
        provided = request.headers.get("x-verifund-fake-webhook", "")
        if not settings.fake_webhook_secret or not secrets.compare_digest(
            provided, settings.fake_webhook_secret
        ):
            raise VerifundError(
                "unauthorized", "fake webhook secret is required", status_code=401
            )
        verified = False
    else:
        async with provider_boundary():
            verified = await request.app.state.payments.verify_webhook(
                request.headers, raw
            )
        if not verified:
            raise VerifundError(
                "unauthorized",
                "PayPal webhook signature is invalid",
                status_code=401,
            )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise VerifundError(
            "invalid_request", "webhook body is not JSON", status_code=400
        ) from exc
    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("event_type") or "")
    if not event_id or not event_type:
        raise VerifundError(
            "invalid_request", "webhook event id and type are required", status_code=400
        )
    resource = payload.get("resource") or {}
    resource_id = resource.get("id")
    repo = request.app.state.repo
    async with repo.transaction() as conn:
        created = await repo.insert_webhook_event(
            conn,
            event_id,
            event_type,
            str(resource_id) if resource_id else None,
            sha256_hex(raw),
            payload,
            settings.mode,
            verified,
        )
    await checkpoint()
    if not created:
        return {"status": "duplicate", "verified": verified}
    try:
        status = await dispatch(request.app.state.service, payload)
    except VerifundError as exc:
        await repo.mark_webhook_event(event_id, "failed", last_error=exc.message)
        await checkpoint()
        raise
    except Exception as exc:
        await repo.mark_webhook_event(
            event_id, "failed", last_error=type(exc).__name__
        )
        await checkpoint()
        raise VerifundError(
            "internal", "webhook processing failed", status_code=500
        ) from exc
    await repo.mark_webhook_event(event_id, status)
    return {"status": status, "verified": verified}
```

import `provider_boundary` and `checkpoint` from
`verifund_control_plane.uow`.

- [ ] **Step 2: Add a webhook boundary test**

Remove the `from verifund_control_plane.uow import current_uow` line and add to
`tests/integration/test_verifund_provider_boundaries.py`:

```python
async def test_webhook_event_survives_a_dispatch_failure(
    control_plane_client, control_plane_app, db_conn, monkeypatch
) -> None:
    from sqlalchemy import text

    from verifund_control_plane.api import webhooks as webhooks_module

    async def boom(service, payload):
        raise RuntimeError("dispatch exploded")

    monkeypatch.setattr(webhooks_module, "dispatch", boom)
    resp = await control_plane_client.post(
        "/webhooks/paypal",
        content=b'{"id": "evt-dispatch-failure", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "cap-1"}}',
        headers={
            "x-verifund-fake-webhook": "dev-verifund-fake-webhook",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 500
    row = (
        await db_conn.execute(
            text("select status, event_id from webhook_events where event_id = :id"),
            {"id": "evt-dispatch-failure"},
        )
    ).first()
    assert row is not None
    assert row.status == "failed"
```

`db_conn` runs in its own service-role transaction and sees committed rows.

And a success-path mark test:

```python
async def test_webhook_dispatch_success_marks_the_event(
    control_plane_client, db_conn, monkeypatch
) -> None:
    from sqlalchemy import text

    from verifund_control_plane.api import webhooks as webhooks_module

    async def ok(service, payload):
        return "processed"

    monkeypatch.setattr(webhooks_module, "dispatch", ok)
    resp = await control_plane_client.post(
        "/webhooks/paypal",
        content=b'{"id": "evt-dispatch-ok", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "cap-1"}}',
        headers={
            "x-verifund-fake-webhook": "dev-verifund-fake-webhook",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    row = (
        await db_conn.execute(
            text("select status from webhook_events where event_id = :id"),
            {"id": "evt-dispatch-ok"},
        )
    ).first()
    assert row.status == "processed"
```

- [ ] **Step 3: Run the webhook boundary tests**

Run: `uv run pytest tests/integration/test_verifund_provider_boundaries.py -q`

Expected: PASS (the two new tests and both fund tests).

- [ ] **Step 4: Bind the reconciler to short service-role units of work**

Change the constructor:

```python
        scanner: Any = None,
        tenancy: Any = None,
        service_engine: Any = None,
    ) -> None:
        ...
        self._service_engine = service_engine
```

Add:

```python
    @asynccontextmanager
    async def _unit_of_work(self):
        if self._service_engine is None:
            yield None
            return
        async with UnitOfWork(self._service_engine) as uow:
            token = bind_uow(uow)
            try:
                yield uow
            finally:
                reset_uow(token)
```

import `asynccontextmanager`, `UnitOfWork`, `bind_uow`, `reset_uow`.

`run_once` becomes:

```python
    async def run_once(self) -> dict[str, int]:
        run_id = new_uuid()
        started_at = self._now()
        ...
        try:
            await self._safe(stats, self._sweep_funding(stats))
            ... unchanged list ...
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            async with self._unit_of_work():
                await self.repo.save_reconciler_run(
                    run_id, started_at, self._now(), stats, error
                )
        return stats
```

`save_reconciler_run` must take a connection or bind to the current UoW; Task 15 already converted it with `self._conn()`, so it works as-is inside the short UoW.

For every sweep, apply the same pattern — a short candidate read, then a fresh UoW per record, exceptions recorded per record:

```python
    async def _sweep_funding(self, stats: dict[str, int]) -> None:
        async with self._unit_of_work():
            records = await self.repo.list_transactions(state="FUNDING_PENDING")
        for record in records:
            try:
                async with self._unit_of_work():
                    funding = record.funding or {}
                    if funding.get("provider_order_id"):
                        await self.service.refresh_funding(
                            record.transaction_id, actor="reconciler"
                        )
                        stats["funding_checked"] += 1
                        continue
                    operation = await self.repo.find_started_operation(
                        record.transaction_id, "create_order"
                    )
                    if operation is not None and await self.service.recover_operation(
                        operation, actor="reconciler"
                    ):
                        stats["provider_intents_recovered"] += 1
                        self._recovered_this_run.add(
                            str(operation.get("operation_id"))
                        )
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
```

Apply the identical treatment to `_sweep_payouts`, `_sweep_trackers`, `_sweep_deadlines`, `_sweep_scans`, `_sweep_remediation`, `_sweep_release_permitted`, `_sweep_deemed_acceptance`, `_sweep_receipts`, `_sweep_ledger`, `_sweep_provider_intents`, and `_sweep_agreements`. When a method already uses `async with self.repo.transaction() as conn:` inside the per-record UoW (remediation, scans, agreements), keep the block — it is the same UoW, not a nested transaction. `_sweep_webhooks` becomes:

```python
    async def _sweep_webhooks(self, stats: dict[str, int]) -> None:
        seen: set[str] = set()
        for status in ("failed", "unmatched", "pending"):
            async with self._unit_of_work():
                events = await self.repo.list_webhook_events(status=status)
            for event in events:
                if event["event_id"] in seen:
                    continue
                seen.add(event["event_id"])
                try:
                    async with self._unit_of_work():
                        outcome = await self.webhook_dispatch(
                            self.service, event["payload"]
                        )
                        await self.repo.mark_webhook_event(
                            event["event_id"], outcome
                        )
                    stats["webhooks_retried"] += 1
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
```

- [ ] **Step 5: Pass the engine from the app**

In `app.py`, construction of the reconciler becomes:

```python
    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=settings,
        clock=now,
        tenancy=tenancy,
        service_engine=service_engine,
    )
```

- [ ] **Step 6: Add the reconciler UoW test**

```python
# tests/integration/test_reconciler_unit_of_work.py
from datetime import UTC, datetime

from sqlalchemy import func, select

from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.reconciler import Reconciler
from verifund_control_plane.repository import Repository
from verifund_control_plane.uow import UnitOfWork


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def refresh_funding(self, transaction_id, *, actor):
        self.calls.append(("refresh_funding", transaction_id))
        return {}

    async def refresh_payout(self, transaction_id, *, actor):
        self.calls.append(("refresh_payout", transaction_id))
        return {}

    async def refresh_tracker(self, transaction_id):
        return None

    async def verify(self, transaction_id, *, actor):
        return {}

    async def backfill_receipt(self, transaction_id, *, actor):
        return False


class _FakeSettings:
    reconciler_pending_seconds = 0
    payout_alert_hours = 1
    reconciler_interval_seconds = 0
    scan_pending_timeout_minutes = 60


async def test_run_once_writes_the_reconciler_run_row(
    control_plane_database, clean_control_plane
) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    reconciler = Reconciler(
        repo=Repository(),
        service=_FakeService(),
        settings=_FakeSettings(),
        clock=lambda: datetime.now(UTC),
        tenancy=None,
        service_engine=engine,
    )
    stats = await reconciler.run_once()
    assert isinstance(stats, dict)
    async with UnitOfWork(engine) as uow:
        count = await uow.connection.scalar(
            select(func.count()).select_from(schema.reconciler_runs)
        )
    assert count == 1
    await engine.dispose()
```

The test also pins the contract that a reconciler constructed without a
service engine keeps working against in-memory fakes, which is what
`tests/unit/test_verifund_reconciler.py` relies on. The empty workload must
not raise: every sweep reads zero rows and the run row is still written.

- [ ] **Step 7: Convert the reconciler unit test expectations**

`tests/unit/test_verifund_reconciler.py` passes a stub repo and service with
no `service_engine`; the new constructor keeps `service_engine` optional and
`_unit_of_work()` yields `None`, so this file needs no changes. Do not import
PostgreSQL there.

- [ ] **Step 8: Run the reconciler suites**

Run:

```bash
uv run pytest tests/unit/test_verifund_reconciler.py tests/integration/test_reconciler_unit_of_work.py tests/integration/test_verifund_provider_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/webhooks.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/app.py tests/integration/test_reconciler_unit_of_work.py tests/integration/test_verifund_provider_boundaries.py
git commit -m "feat: bind webhook and reconciler work to short units of work"
```

---

## Milestone 6 — Test Port and RLS Completion

### Task 25: Convert the control-plane test suite to PostgreSQL

**Files:**
- Modify the app-level tests:
  `tests/integration/test_verifund_funding.py`,
  `tests/integration/test_verifund_lifecycle.py`,
  `tests/integration/test_verifund_seller_api.py`,
  `tests/integration/test_verifund_webhooks.py`,
  `tests/integration/test_verifund_reconciler.py`,
  `tests/unit/test_verifund_upload.py`,
  `tests/unit/test_verifund_seller_reads.py`,
  `tests/unit/test_verifund_buyer_api.py`,
  `tests/unit/test_verifund_declarations.py`,
  `tests/unit/test_verifund_attach_funding_order.py`,
  `tests/unit/test_verifund_capture_attempt_key.py`,
  `tests/unit/test_verifund_prepare_funding.py`,
  `tests/unit/test_verifund_prepare_attach_routes.py`,
  `tests/unit/test_verifund_paypal_tracking.py`,
  `tests/unit/test_verifund_service.py`,
  `tests/unit/test_verifund_settings.py`,
  `tests/unit/test_clerk_webhooks.py`,
  `tests/unit/test_ops_narrowing.py`,
  `tests/unit/test_platform_admin.py`,
  `tests/unit/test_tenant_columns.py`,
  `tests/unit/test_tenant_isolation.py`,
  `tests/unit/test_seller_gate.py`,
  `tests/unit/test_tenancy_identity.py`,
  `tests/unit/test_verifund_reconciler.py` (no changes; pure fakes)
- Modify the direct-DB tests:
  `tests/unit/test_agent_audit.py`,
  `tests/unit/test_agent_credentials.py`,
  `tests/unit/test_agent_lifecycle.py`,
  `tests/unit/test_agent_test_gate.py`,
  `tests/unit/test_audit_scope.py`,
  `tests/unit/test_evidence_tenant.py`,
  `tests/unit/test_seller_onboarding.py`,
  `tests/unit/test_tenancy_sync.py`,
  `tests/unit/test_transaction_access.py`
- Not in this task (already converted): repository/RLS/role/identity tests
  (Tasks 3, 15–21, 23, 24), seed (Task 19), fake payments (Task 23).
- Not in this task, ever: buyer agent, seller agent, registry, orchestrator,
  verifund agent, and `tests/support/servers.py` keep SQLite until their
  plans:
  - registry: `tests/integration/test_registry.py`,
    `tests/unit/test_registry_agents.py`, `tests/unit/test_registry_projection.py`;
  - buyer agent: `tests/integration/test_a2a_v03_compat.py`,
    `tests/integration/test_buyer_discovery.py`,
    `tests/integration/test_buyer_server.py`,
    `tests/protocol/test_mediation_gate.py`, `tests/support/servers.py`,
    `tests/unit/test_buyer_settlement_store.py`, `tests/unit/test_runs_tenancy.py`,
    `tests/unit/test_stream_auth.py`, `tests/unit/test_trace_redaction.py`;
  - seller agent: `tests/unit/test_seller_agreement_review.py`,
    `tests/unit/test_seller_evidence_flow.py`,
    `tests/unit/test_seller_evidence_outbox.py`,
    `tests/unit/test_seller_settlement_validation.py`;
  - orchestrator: `tests/unit/test_orchestrator_server.py`;
  - verifund agent: `tests/unit/test_verifund_agent_package.py`;
  - scripts/config: `tests/unit/test_verifund_packaging.py`,
    `tests/unit/test_verifund_dev_config.py`,
    `tests/unit/test_verifund_scripts.py` (updated in Task 28);
  - `tests/unit/test_tenancy_backfill.py` (deleted in Task 28).

**Interfaces:**
- App-level tests use the shared `control_plane_app` / `control_plane_client`
  fixtures and `control_plane_settings(control_plane_database, ...)` from
  Task 20.
- Direct-DB tests use `db_conn` (service-role rollback transaction) or a
  `UnitOfWork` over `control_plane_database.service_url` with `bind_uow`.
- Tests that insert a transaction row must use valid UUID literals such as
  `TXN = "44444444-4444-4444-8444-444444444444"`; business-facing prefixed
  IDs in HTTP paths (e.g. `/transactions/vf-1/state`) remain legal strings.

- [ ] **Step 1: Convert the app-level integration tests**

For each file in the group, apply the same recipe:

1. Delete the local `tmp_path` Settings/create_app fixture.
2. Add `from tests.support.award_flow import NOW` if the file uses `NOW`.
3. Replace the fixture with:
   ```python
   @pytest.fixture
   async def api(control_plane_client):
       yield control_plane_client
   ```
   or simply rename the parameter to `control_plane_client` and update call
   sites. Keep the test body untouched otherwise.
4. Where a test reads app state for direct DB assertions, use
   `control_plane_app.state.repo` inside a `UnitOfWork` bound via `bind_uow`,
   or a fresh `UnitOfWork` over `control_plane_database.service_url`; before
   calling repositories, bind the unit of work with `bind_uow` and reset
   afterwards.
5. Fix assertions on generated IDs: read the ID from the response instead of
   matching a prefix. Example: `assert len(body["transaction_id"]) == 36`.
6. `settle_scans_and_verify` and `seed_system_delivery` in
   `test_verifund_lifecycle.py` run raw SQL/repo calls; keep them, adapting
   only the engine/fixture wiring:
   ```python
   async def settle_scans_and_verify(api, transaction_id: str) -> None:
       app = api._transport.app
       ...
   ```
   `api._transport.app` still works because `control_plane_client` uses
   `httpx.ASGITransport`, so the reference remains valid.

Run after each file: `uv run pytest <file> -q`. Expected: PASS.

- [ ] **Step 2: Convert `tests/unit/test_verifund_settings.py`**

1. Add the four URLs to the `sandbox_settings` helper and to
   `test_default_mode_is_sandbox`:
   ```python
   BASE_URLS = {
       "database_url": "postgresql+psycopg://cp_app@localhost/db",
       "auth_database_url": "postgresql+psycopg://cp_auth@localhost/db",
       "service_database_url": "postgresql+psycopg://cp_service@localhost/db",
       "database_url_unpooled": "postgresql+psycopg://cp_migrator@localhost/db",
   }
   ```
   `sandbox_settings` becomes `values = {..., **BASE_URLS}` and
   `Settings(_env_file=None, **BASE_URLS).mode` in the default-mode test.
2. Replace `test_health_and_ready` with the shared fixtures:
   ```python
   async def test_health_and_ready(control_plane_client) -> None:
       assert (await control_plane_client.get("/health")).json()["status"] == "ok"
       assert (await control_plane_client.get("/ready")).status_code == 200
   ```

- [ ] **Step 3: Convert the app-level unit tests**

Apply the Step 1 recipe to the unit files listed above. Watch for:

- `tests/unit/test_verifund_buyer_api.py` — `app.state.buyer_tokens.issue("demo-buyer", "vf_1")` writes `buyer_tokens.transaction_id = "vf_1"`, which is invalid for the `UUIDStr` column. Replace `"vf_1"` with a fixed UUID constant such as `TXN = "44444444-4444-4444-8444-444444444444"` everywhere in the file, and seed the matching transaction row through `Repository` or `schema.transactions.insert()` if the test reads it back.
- `tests/unit/test_verifund_declarations.py` — declaration rows must be written
  with valid UUID `submission_id`s; the `requirement_declarations.submission_ids`
  assertion now checks join-table rows:
  ```python
  rows = (
      await conn.execute(
          select(schema.requirement_declaration_submissions).where(
              schema.requirement_declaration_submissions.c.declaration_id == declaration_id
          )
      )
  ).all()
  assert {row.submission_id for row in rows} == expected_submission_ids
  ```
  `submission_id`s are `UUIDStr`, so any `sub_...` literals must become UUIDs.
- `tests/unit/test_verifund_fake_payments.py` — already converted in Task 23.
- `tests/unit/test_ops_narrowing.py` — its SQLite `update()` against the
  evidence table passes `scan_status="clean"`; keep it but run it through
  `UnitOfWork(service_engine)` + `bind_uow` instead of raw `repo.transaction()`
  or an engine.
- `tests/unit/test_tenant_isolation.py` — creates separate clients for two
  seller side; reuse the shared fixture, no code changes inside test bodies.

- [ ] **Step 4: Convert the direct-DB unit tests**

Same recipe as Tasks 15–17:

1. Replace SQLite engines with `control_plane_database.service_url` and remove
   `store.create_schema()` / `repo.create_schema()` calls.
2. For repositories methods that accept `conn`, pass `db_conn`.
3. For other repositories, wrap calls in `UnitOfWork(engine)` + `bind_uow` and
   reset after.
4. For tests that assert raw SQL values, use `db_conn`.

Run each file after converting it.

- [ ] **Step 5: Prove the sweep is complete**

Run:

```bash
grep -rli 'sqlite' tests/unit tests/integration tests/protocol tests/support | sort
```

Expected: every file in the output appears in the exclusion list above. If a
control-plane file appears there, convert it. Then:

```bash
grep -rn 'create_schema' apps/verifund_control_plane tests/unit tests/integration
grep -rn 'verifund_control_plane.db' apps tests
```

Expected: no matches.

- [ ] **Step 6: Run the full control-plane suite**

```bash
docker compose up -d postgres
uv run pytest tests/unit tests/integration tests/protocol -q
```

Expected: everything passes except the intentionally untouched SQLite suites
(which still run and still use SQLite) — the total failure count must be zero.

Commit in three reviewable chunks:

```bash
git add tests/integration/test_verifund_*.py
git commit -m "test: run verifund integration tests against postgres"
git add tests/unit/test_verifund_*.py tests/unit/test_verifund_settings.py tests/unit/test_clerk_webhooks.py tests/unit/test_ops_narrowing.py tests/unit/test_platform_admin.py tests/unit/test_tenant_columns.py tests/unit/test_tenant_isolation.py tests/unit/test_seller_gate.py tests/unit/test_tenancy_identity.py
git commit -m "test: run verifund app unit tests against postgres"
git add tests/unit/test_agent_*.py tests/unit/test_audit_scope.py tests/unit/test_evidence_tenant.py tests/unit/test_seller_onboarding.py tests/unit/test_tenancy_sync.py tests/unit/test_transaction_access.py
git commit -m "test: run verifund direct-db unit tests against postgres"
```

---

### Task 26: Close the RLS policy gaps and add the policy matrix test

**Files:**
- Modify: `apps/verifund_control_plane/migrations/versions/0003_rls_policies.py`
- Create: `tests/integration/test_control_plane_rls_matrix.py`

**Interfaces:**
- `requirement_declarations` gets its own org-or-parent policy (it is a
  transaction child that Task 14 missed). Agreement children and
  `requirement_declaration_submissions` stay as written in Task 14.
- Migration revision stays `0003_rls_policies` — it has never shipped to any
  environment; editing it in place is correct. Do not create a `0004`.
- The matrix test asserts the exact set of forced-RLS tables, the exact
  policy count, cross-tenant write rejection for a representative table of
  each shape (dual-org, single-org, transaction child, agreement child,
  join table), and the `information_schema.role_table_grants` matrix for
  `cp_app`/`cp_auth`/`cp_service`.

- [ ] **Step 1: Fix `0003_rls_policies.py` before it ships**

Add `requirement_declarations` to the migration (it is a transaction child):

```python
def upgrade() -> None:
    ...
    for table in TRANSACTION_CHILD_TABLES:
        _enable(table)
        exists = _parent_exists(table, "transactions", "transaction_id")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL TO cp_app "
            f"USING ({exists}) WITH CHECK ({exists})"
        )

    _enable("requirement_declarations")
    declaration_exists = (
        "EXISTS (SELECT 1 FROM transactions t "
        "WHERE t.transaction_id = requirement_declarations.transaction_id "
        f"AND (t.buyer_organization_id = {TENANT} "
        f"OR t.seller_organization_id = {TENANT}))"
    )
    op.execute(
        "CREATE POLICY requirement_declarations_tenant "
        "ON requirement_declarations FOR ALL TO cp_app "
        f"USING ({declaration_exists}) WITH CHECK ({declaration_exists})"
    )
    ...
```

And add `"requirement_declarations"` to the `downgrade()` table list. The
exact emitted `_parent_exists` SQL must be checked by hand before running —
write it out explicitly (do not rely on the f-string alias replacement). The
required predicate text is:

```sql
EXISTS (
  SELECT 1 FROM transactions p
  WHERE p.transaction_id = requirement_declarations.transaction_id
    AND (p.buyer_organization_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
         OR p.seller_organization_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
)
```

- [ ] **Step 2: Write the matrix test**

```python
# tests/integration/test_control_plane_rls_matrix.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from verifund_control_plane import schema
from verifund_control_plane.pg import create_postgres_engine
from verifund_control_plane.uow import UnitOfWork

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
ORG_S = "33333333-3333-4333-8333-333333333333"
USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TXN_SHARED = "44444444-4444-4444-8444-444444444444"
TXN_B = "55555555-5555-4555-8555-555555555555"
AGR_SHARED = "66666666-6666-4666-8666-666666666666"
AGR_B = "77777777-7777-4777-8777-777777777777"
DECL_SHARED = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

EXPECTED_FORCED_TABLES = {
    "transactions", "agreements",
    "seller_profiles", "buyer_profiles", "seller_onboarding",
    "seller_verifications", "agents", "agent_credentials", "agent_test_runs",
    "payment_accounts", "payout_releases", "organization_invitations",
    "organizations",
    "transaction_events", "ledger_entries", "evidence_submissions",
    "provider_operations", "payout_items", "receipts", "seller_tokens",
    "buyer_tokens", "invitation_tokens", "checkout_links",
    "requirement_declarations", "requirement_declaration_submissions",
    "agreement_versions", "agreement_decisions", "agreement_change_requests",
    "agreement_approval_tokens", "agreement_events",
    "evidence", "audit_log",
}
EXPECTED_POLICY_COUNT = 32


async def seed(control_plane_database) -> None:
    engine = create_postgres_engine(control_plane_database.service_url)
    async with UnitOfWork(engine) as uow:
        conn = uow.connection
        now = NOW
        await conn.execute(
            schema.organizations.insert(),
            [
                {"id": ORG_A, "kind": "business", "name": "A", "slug": "a",
                 "status": "active", "owner_user_id": USER_A,
                 "created_at": now, "updated_at": now},
                {"id": ORG_B, "kind": "business", "name": "B", "slug": "b",
                 "status": "active", "owner_user_id": USER_A,
                 "created_at": now, "updated_at": now},
                {"id": ORG_S, "kind": "business", "name": "S", "slug": "s",
                 "status": "active", "owner_user_id": USER_A,
                 "created_at": now, "updated_at": now},
            ],
        )
        common = {
            "run_id": "run-1", "offer_id": "offer-1", "state": "AWARDED",
            "version": 1, "last_seq": 0, "amount_cents": 1000, "currency": "USD",
            "agreement_hash": "a" * 64, "agreement_version": 1, "deadlines": {},
            "created_at": now, "updated_at": now,
        }
        await conn.execute(
            schema.transactions.insert(),
            [
                {**common, "transaction_id": TXN_SHARED, "buyer_id": "buyer-a",
                 "seller_id": "seller-s", "buyer_organization_id": ORG_A,
                 "seller_organization_id": ORG_S, "agreement_id": AGR_SHARED},
                {**common, "transaction_id": TXN_B, "buyer_id": "buyer-b",
                 "seller_id": "seller-s", "buyer_organization_id": ORG_B,
                 "seller_organization_id": ORG_S, "agreement_id": AGR_B},
            ],
        )
        agreement_common = {
            "run_id": "run-1", "seller_id": "seller-s", "current_version": 1,
            "status": "PENDING_SELLER", "offer_id": "offer-1", "offer_round": 1,
            "offer_hash": "b" * 64, "offer_valid_until": now, "row_version": 1,
            "seller_operator_required": False, "created_at": now, "updated_at": now,
        }
        await conn.execute(
            schema.agreements.insert(),
            [
                {**agreement_common, "agreement_id": AGR_SHARED,
                 "transaction_id": TXN_SHARED, "buyer_id": "buyer-a",
                 "buyer_organization_id": ORG_A, "seller_organization_id": ORG_S},
                {**agreement_common, "agreement_id": AGR_B,
                 "transaction_id": TXN_B, "buyer_id": "buyer-b",
                 "buyer_organization_id": ORG_B, "seller_organization_id": ORG_S},
            ],
        )
        await conn.execute(
            schema.requirement_declarations.insert().values(
                declaration_id=DECL_SHARED,
                transaction_id=TXN_SHARED,
                requirement_id="shipping",
                attempt=1,
                actor="seller-s",
                declared_at=now,
            )
        )
    await engine.dispose()


@pytest.fixture
async def seeded(control_plane_database):
    await seed(control_plane_database)
    return control_plane_database


async def test_exact_forced_rls_table_set(seeded) -> None:
    engine = create_postgres_engine(seeded.migrator_url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select relname from pg_class "
                    "where relrowsecurity and relforcerowsecurity "
                    "and relkind = 'r'"
                )
            )
        ).all()
        relnames = {row.relname for row in rows}
    await engine.dispose()
    assert relnames == EXPECTED_FORCED_TABLES


async def test_policy_count_matches(seeded) -> None:
    engine = create_postgres_engine(seeded.migrator_url)
    async with engine.connect() as conn:
        count = await conn.scalar(
            text(
                "select count(*) from pg_policies "
                "where schemaname = 'public' and policyname like '%\\_tenant'"
            )
        )
    await engine.dispose()
    assert count == EXPECTED_POLICY_COUNT


async def _can_insert_declaration(database, tenant: str, transaction_id: str) -> bool:
    engine = create_postgres_engine(database.app_url)
    try:
        async with UnitOfWork(engine, tenant_id=tenant) as uow:
            await uow.connection.execute(
                schema.requirement_declarations.insert().values(
                    declaration_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                    transaction_id=transaction_id,
                    requirement_id="shipping",
                    attempt=2,
                    actor="seller-s",
                    declared_at=NOW,
                )
            )
        return True
    except DBAPIError:
        return False
    finally:
        await engine.dispose()


async def test_requirement_declarations_follow_their_transaction(seeded) -> None:
    assert await _can_insert_declaration(seeded, ORG_A, TXN_SHARED) is True
    assert await _can_insert_declaration(seeded, ORG_B, TXN_B) is True
    assert await _can_insert_declaration(seeded, ORG_A, TXN_B) is False
    assert await _can_insert_declaration(seeded, ORG_B, TXN_SHARED) is False


async def _update_agreement_child(database, tenant: str) -> bool:
    engine = create_postgres_engine(database.app_url)
    try:
        async with UnitOfWork(engine, tenant_id=tenant) as uow:
            await uow.connection.execute(
                schema.agreement_versions.update()
                .where(schema.agreement_versions.c.agreement_id == AGR_SHARED)
                .values(row_version=99)
            )
        return True
    except DBAPIError:
        return False
    finally:
        await engine.dispose()


async def test_agreement_children_are_tenant_guarded(seeded) -> None:
    engine = create_postgres_engine(seeded.service_url)
    async with UnitOfWork(engine) as uow:
        await uow.connection.execute(
            schema.agreement_versions.insert().values(
                agreement_id=AGR_SHARED, version=1, renderer_version="1",
                title="T", terms={}, agreement_hash="c" * 64,
                created_at=NOW,
            )
        )
    await engine.dispose()
    assert await _update_agreement_child(seeded, ORG_S) is True


async def test_grant_matrix(seeded) -> None:
    engine = create_postgres_engine(seeded.migrator_url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select grantee, table_name, privilege_type "
                    "from information_schema.role_table_grants "
                    "where grantee in ('cp_app', 'cp_auth', 'cp_service')"
                )
            )
        ).all()
    await engine.dispose()
    grants: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        grants.setdefault(row.grantee, {}).setdefault(row.table_name, set()).add(
            row.privilege_type
        )
    for table in ("idempotency_keys", "webhook_events", "reconciler_runs", "fake_orders"):
        assert "cp_app" not in grants or table not in grants["cp_app"]
        assert grants.get("cp_service", {}).get(table) == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert set(grants.get("cp_auth", {}).keys()) == {
        "users", "organizations", "organization_members", "platform_admins"
    }
    assert all(
        privileges == {"SELECT"} for privileges in grants.get("cp_auth", {}).values()
    )
```

The `cp_service` grant assertion must match what `0002_roles_grants` actually
issues (it grants `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES`). Verify the
information_schema output by hand once; adjust the expected set to the real
grant if it differs, not the migration. The `agreement_versions` insert
columns mirror the Task 11 schema (`terms`, `renderer_version`, `title`,
`agreement_hash`); if Task 11's real column list differs, copy the real
definition — the point is one tenant can update its agreement child row and a
foreign tenant cannot. Add the foreign case after seeding a version for
`AGR_B` as well and asserting `_update_agreement_child(seeded, ORG_A)` is
False for it.

The `EXPECTED_POLICY_COUNT = 32` is exact: 2 dual-org + 10 single-org + 1
organizations + 10 transaction children + 1 requirement_declarations + 1
requirement_declaration_submissions + 5 agreement children + evidence + audit_log.

- [ ] **Step 3: Run the migration/role/RLS suites**

```bash
uv run pytest tests/integration/test_control_plane_migration.py \
  tests/integration/test_control_plane_roles.py \
  tests/integration/test_control_plane_rls.py \
  tests/integration/test_control_plane_rls_matrix.py -q
```

Expected: PASS. If `test_policy_count_matches` fails, list the policies with
`select policyname from pg_policies` and reconcile against the migration —
never edit the assertion to match a broken migration. If
`test_exact_forced_rls_table_set` fails, either a table is missing from the
migration (add it) or an unexpected table is forced (drop it deliberately,
with a comment, not silently).

- [ ] **Step 4: Commit**

```bash
git add apps/verifund_control_plane/migrations/versions/0003_rls_policies.py tests/integration/test_control_plane_rls_matrix.py
git commit -m "feat: close the rls policy gaps and cover the policy matrix"
```

---

### Task 27: Prove the PostgreSQL lifecycle end to end

**Files:**
- Create: `tests/integration/test_control_plane_lifecycle_postgres.py`

**Interfaces:**
- The full fake-provider lifecycle works against a clean PostgreSQL database.
- A control-plane restart against the same database preserves state.
- Startup fails fast on an unmigrated database.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/integration/test_control_plane_lifecycle_postgres.py
import httpx
import pytest

from tests.support.award_flow import (
    NOW,
    OPS,
    accept,
    approve,
    award,
    fund_and_capture,
)
from tests.support.postgres import (
    control_plane_settings,
    create_test_database,
    drop_test_database,
)
from verifund_control_plane.app import create_app


async def test_fake_lifecycle_reaches_funded_in_a_clean_database(
    control_plane_client, control_plane_app
) -> None:
    body = await award(control_plane_client)
    assert len(body["transaction_id"]) == 36  # native UUID, no prefix
    await accept(control_plane_client, body)
    await approve(control_plane_client, body)
    await fund_and_capture(control_plane_client, body)
    state = (
        await control_plane_client.get(
            f"/transactions/{body['transaction_id']}/state", headers=OPS
        )
    ).json()
    assert state["state"] == "FUNDED"
    assert state["funding"]["status"] == "captured"


async def test_state_survives_an_app_restart(
    control_plane_database, clean_control_plane, tmp_path
) -> None:
    settings = control_plane_settings(
        control_plane_database, evidence_dir=tmp_path / "evidence-1"
    )
    app1 = create_app(settings, clock=lambda: NOW)
    transaction_id = None
    async with app1.router.lifespan_context(app1):
        transport = httpx.ASGITransport(app=app1)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            body = await award(client)
            transaction_id = body["transaction_id"]
            accept_body = body
            await accept(client, accept_body)
            await approve(client, accept_body)

    assert transaction_id is not None

    settings2 = control_plane_settings(
        control_plane_database, evidence_dir=tmp_path / "evidence-2"
    )
    app2 = create_app(settings2, clock=lambda: NOW)
    async with app2.router.lifespan_context(app2):
        transport = httpx.ASGITransport(app=app2)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            state = (
                await client.get(
                    f"/transactions/{transaction_id}/state", headers=OPS
                )
            ).json()
            assert state["state"] == "AGREED"
            assert state["approval"]["approval_id"] == "apr-1"
            events = (
                await client.get(
                    f"/transactions/{transaction_id}/events", headers=OPS
                )
            ).json()
            assert len(events) >= 3
            await fund_and_capture(client, accept_body)
            funded = (
                await client.get(
                    f"/transactions/{transaction_id}/state", headers=OPS
                )
            ).json()
            assert funded["state"] == "FUNDED"


async def test_startup_fails_fast_on_an_unmigrated_database(tmp_path) -> None:
    database = await create_test_database("verifund_control_plane_smoke_test")
    try:
        settings = control_plane_settings(
            database, evidence_dir=tmp_path / "evidence"
        )
        app = create_app(settings, clock=lambda: NOW)
        with pytest.raises(RuntimeError, match="not migrated"):
            async with app.router.lifespan_context(app):
                pass
    finally:
        await drop_test_database(database)
```

Notes:

- `test_state_survives_an_app_restart` proves the lifecycle crosses a
  "redeploy": two independent app instances against the same migrated
  database. The fake provider's `fake_orders` rows are service-role data
  created by the first instance on its funding call; the fresh instance reads
  them back through the shared `verifund_control_plane_test` database, which
  is what makes restart persistence observable.
- `accept_body` is passed to `fund_and_capture` in the second instance; the
  award body already carries `agreement_hash` and `agreement_version`, which
  `fund_and_capture` reads from it.
- `test_startup_fails_fast_on_an_unmigrated_database` creates a scratch
  database without running Alembic; `assert_schema_revision` must raise
  `RuntimeError` inside the lifespan, and the test must drop the scratch
  database in `finally`.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/integration/test_control_plane_lifecycle_postgres.py -q`

Expected: FAIL — `test_fake_lifecycle_reaches_funded_in_a_clean_database`
fails on the evidence upload path or on an unexpected generated prefix before
Task 25/26 land, and the file may be absent of any other failure. If every
assertion already holds, the test is a characterization of completed work;
that is fine, but check that `test_startup_fails_fast_on_an_unmigrated_database`
fails for the right reason (lifespan raises `RuntimeError`, not
`ModuleNotFoundError`).

- [ ] **Step 3: Confirm the test passes with Tasks 22–26 complete**

Run: `uv run pytest tests/integration/test_control_plane_lifecycle_postgres.py -q`

Expected: PASS, 3 tests.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_control_plane_lifecycle_postgres.py
git commit -m "test: pin the postgres lifecycle across restarts"
```

---

### Task 28: Delete the SQLite control-plane paths and update packaging and docs

**Files:**
- Delete: `apps/verifund_control_plane/verifund_control_plane/db.py`
- Delete: `apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py`
- Delete: `tests/unit/test_tenancy_backfill.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `scripts/config.py`
- Modify: `scripts/dev.py`
- Modify: `scripts/verifund_smoke.py`
- Modify: `scripts/provision_control_plane_roles.py` (add `ensure_database`)
- Modify: `tests/unit/test_verifund_packaging.py`
- Modify: `tests/unit/test_verifund_dev_config.py`
- Modify: `tests/unit/test_verifund_scripts.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/runbook.md`
- Modify: `docs/verifund-paypal-sandbox.md`

**Interfaces:**
- `scripts/provision_control_plane_roles.py` gains
  `ensure_database(admin_url, database)`: create the target database if
  missing and set `cp_migrator` as its owner. The CLI gains
  `--create-database` (default on) so one command prepares a fresh local
  deployment.
- Compose gains `postgres` (already added in Task 2), `verifund-roles`,
  `verifund-migrate`, `verifund-seed` one-shots, and the `verifund` service
  depends on all three. All control-plane traffic in Compose points at the
  Compose Postgres; other services keep SQLite until their plans.
- `.env.example` documents the four role URLs and points `VERIFUND_DATABASE_URL`
  at local Compose Postgres.
- `scripts/config.py`: `verifund_database_url()` is replaced by
  `verifund_database_urls()` returning the four URLs (used by `scripts/dev.py`
  to set the control-plane environment).
- `scripts/verifund_smoke.py`: boots the control plane against a scratch
  `verifund_smoke_test` database created through the test harness.

- [ ] **Step 1: Delete the SQLite code and its tests**

```bash
git rm apps/verifund_control_plane/verifund_control_plane/db.py
git rm apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py
git rm tests/unit/test_tenancy_backfill.py
grep -rn 'verifund_control_plane.db\|tenancy.backfill\|tenancy\.backfill' apps tests scripts Makefile docker-compose.yml README.md docs
```

Expected: no matches after the removals. If a match is found outside the
deleted files, port the caller to the new API in this task.

- [ ] **Step 2: Extend the role provisioner with `ensure_database`**

Add to `scripts/provision_control_plane_roles.py`:

```python
def ensure_database(admin_url: str, database: str) -> None:
    with psycopg.connect(libpq_url(admin_url), autocommit=True) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (database,)
        ).fetchone()
        if not exists:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER cp_migrator").format(
                    sql.Identifier(database)
                )
            )
        else:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO cp_migrator").format(
                    sql.Identifier(database)
                )
            )
```

and wire it into the CLI:

```python
    parser.add_argument("--create-database", action="store_true", default=True)
    if args.create_database:
        ensure_database(args.admin_url, args.database)
    provision(args.admin_url, args.database)
```

`ensure_database` needs the roles to exist, so call them in this order:

```python
    provision(args.admin_url, args.database)
    if args.create_database:
        ensure_database(args.admin_url, args.database)
```

For the local Compose path (`POSTGRES_DB: verifund_control_plane`), the
database already exists and `ensure_database` only reassigns ownership to
`cp_migrator`, which is idempotent.

- [ ] **Step 3: Update `docker-compose.yml`**

Add under `services:` (next to `postgres` from Task 2):

```yaml
  verifund-roles:
    <<: *python-service
    command: >-
      python scripts/provision_control_plane_roles.py
      --admin-url postgresql+psycopg://postgres:postgres@postgres:5432/postgres
      --database verifund_control_plane
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      HOST: 0.0.0.0

  verifund-migrate:
    <<: *python-service
    command: alembic -c apps/verifund_control_plane/alembic.ini upgrade head
    restart: "no"
    depends_on:
      verifund-roles:
        condition: service_completed_successfully
    environment:
      VERIFUND_DATABASE_URL_UNPOOLED: postgresql+psycopg://cp_migrator@postgres:5432/verifund_control_plane

  verifund-seed:
    <<: *python-service
    command: python scripts/seed_control_plane.py --database-url postgresql+psycopg://cp_service@postgres:5432/verifund_control_plane
    restart: "no"
    depends_on:
      verifund-migrate:
        condition: service_completed_successfully
```

Change the `verifund` service environment to:

```yaml
      VERIFUND_DATABASE_URL: postgresql+psycopg://cp_app@postgres:5432/verifund_control_plane
      VERIFUND_AUTH_DATABASE_URL: postgresql+psycopg://cp_auth@postgres:5432/verifund_control_plane
      VERIFUND_SERVICE_DATABASE_URL: postgresql+psycopg://cp_service@postgres:5432/verifund_control_plane
      VERIFUND_DATABASE_URL_UNPOOLED: postgresql+psycopg://cp_migrator@postgres:5432/verifund_control_plane
```

and add to `verifund`:

```yaml
    depends_on:
      verifund-seed:
        condition: service_completed_successfully
```

(If `verifund` already has a `depends_on`, merge the entry.)

- [ ] **Step 4: Update `.env.example`**

Replace the line `VERIFUND_DATABASE_URL=sqlite+aiosqlite:///./data/verifund.db`
with:

```dotenv
# Control plane on PostgreSQL 18 (local Compose or Neon).
# Local Compose uses trust auth on 127.0.0.1:55432 and needs no passwords;
# for Neon use pooled app URLs and the direct migrator URL.
VERIFUND_DATABASE_URL=postgresql+psycopg://cp_app:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_AUTH_DATABASE_URL=postgresql+psycopg://cp_auth:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_SERVICE_DATABASE_URL=postgresql+psycopg://cp_service:change-me@127.0.0.1:55432/verifund_control_plane
VERIFUND_DATABASE_URL_UNPOOLED=postgresql+psycopg://cp_migrator:change-me@127.0.0.1:55432/verifund_control_plane
```

Leave buyer/seller/registry/agent URLs on SQLite — they migrate in plans 2–4.

Note: a local `.env` that still defines
`VERIFUND_DATABASE_URL=sqlite+aiosqlite:///./data/verifund.db` is stale but
harmless — `make dev` and Docker Compose set the four URLs explicitly in the
process environment, and pydantic-settings prefers those over `.env`. Tell the
reader to replace the stale line; do not edit `.env` automatically. `.env` may
also contain a pooled `neondb_owner` credential; it is never used at runtime
(owner role bypasses everything) and must be rotated at cutover.

- [ ] **Step 5: Update `Makefile`**

Add:

```make
verifund-db-up:
	docker compose up -d postgres
	docker compose run --rm verifund-roles
	docker compose run --rm verifund-migrate
	docker compose run --rm verifund-seed
```

and document `make verifund-db-up` in the Services table. Keep all other
targets unchanged.

- [ ] **Step 6: Update `scripts/config.py` and `scripts/dev.py`**

Replace `verifund_database_url()` in `scripts/config.py` with:

```python
def verifund_database_urls() -> dict[str, str]:
    return {
        "VERIFUND_DATABASE_URL": _env(
            "VERIFUND_DATABASE_URL",
            "postgresql+psycopg://cp_app@127.0.0.1:55432/verifund_control_plane",
        ),
        "VERIFUND_AUTH_DATABASE_URL": _env(
            "VERIFUND_AUTH_DATABASE_URL",
            "postgresql+psycopg://cp_auth@127.0.0.1:55432/verifund_control_plane",
        ),
        "VERIFUND_SERVICE_DATABASE_URL": _env(
            "VERIFUND_SERVICE_DATABASE_URL",
            "postgresql+psycopg://cp_service@127.0.0.1:55432/verifund_control_plane",
        ),
        "VERIFUND_DATABASE_URL_UNPOOLED": _env(
            "VERIFUND_DATABASE_URL_UNPOOLED",
            "postgresql+psycopg://cp_migrator@127.0.0.1:55432/verifund_control_plane",
        ),
    }
```

Make sure the old `verifund_database_url` name is gone (update its callers),
and in `scripts/dev.py::control_plane_environment` replace the
`VERIFUND_DATABASE_URL` entry with the four keys:

```python
            **verifund_database_urls(),
```

Add a pre-flight check in `dev.py` before the control plane starts:

```python
def ensure_verifund_postgres() -> None:
    print("Preparing the control-plane database (docker compose postgres)...")
    for cmd in (
        ["docker", "compose", "up", "-d", "postgres"],
        ["docker", "compose", "run", "--rm", "verifund-roles"],
        ["docker", "compose", "run", "--rm", "verifund-migrate"],
        ["docker", "compose", "run", "--rm", "verifund-seed"],
    ):
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(cmd)} failed; start the Compose postgres service "
                "and check .dev-logs"
            )
```

and call it in the verifund startup path only when `VERIFUND_MODE` is not
`off`. Respect an escape hatch: `VERIFUND_SKIP_DB_PREP=1` skips the block.

- [ ] **Step 7: Rewrite the smoke script for PostgreSQL**

Split `scripts/verifund_smoke.py` into a pure environment builder and a
prepare step with side effects (the unit test must not spawn Docker):

```python
def smoke_environment(root: Path, *, port: int) -> dict[str, str]:
    database = os.environ.get("VERIFUND_SMOKE_DATABASE", "verifund_smoke_test")
    base = f"postgresql+psycopg://cp_{{}}@127.0.0.1:55432/{database}"
    return {
        "VERIFUND_MODE": "fake",
        "HOST": "127.0.0.1",
        "VERIFUND_PORT": str(port),
        "VERIFUND_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "VERIFUND_CONSOLE_BASE_URL": "http://127.0.0.1:3000",
        "VERIFUND_DATABASE_URL": base.format("app"),
        "VERIFUND_AUTH_DATABASE_URL": base.format("auth"),
        "VERIFUND_SERVICE_DATABASE_URL": base.format("service"),
        "VERIFUND_DATABASE_URL_UNPOOLED": base.format("migrator"),
        "VERIFUND_EVIDENCE_DIR": str(root / "evidence"),
        "VERIFUND_INSPECTION_WINDOW_HOURS": "0",
        "VERIFUND_RECONCILER_ENABLED": "false",
        "VERIFUND_OPS_TOKEN": "smoke-ops",
        "VERIFUND_SELLER_TOKEN_SECRET": "smoke-seller-token-secret",
        "VERIFUND_LINK_SECRET": "smoke-link-secret",
        "VERIFUND_SELLER_PAYOUT_EMAILS": json.dumps({SELLER_ID: "seller-northwind@example.com"}),
    }


def prepare_smoke_database(*, admin_url: str, database: str) -> None:
    """(Re)create the scratch database, provision roles, migrate, seed."""
    assert database.endswith("_test"), "smoke database must end in _test"
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{database}"')
    env = {**os.environ, "VERIFUND_DATABASE_URL_UNPOOLED":
           f"postgresql+psycopg://cp_migrator@127.0.0.1:55432/{database}"}
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/provision_control_plane_roles.py"),
         "--admin-url", admin_url, "--database", database],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c",
         str(ROOT / "apps/verifund_control_plane/alembic.ini"), "upgrade", "head"],
        check=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed_control_plane.py"),
         "--database-url", f"postgresql+psycopg://cp_service@127.0.0.1:55432/{database}"],
        check=True,
    )
```

`main()` calls `prepare_smoke_database(...)` before spawning uvicorn when
`VERIFUND_MODE` is fake (the default) and treats a connection failure to
127.0.0.1:55432 as a clear error: start the local Compose postgres first
(`docker compose up -d postgres`). Drop `root / 'verifund.db'` handling.

Also update the `tests/unit/test_verifund_scripts.py` assertion:

```python
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_RECONCILER_ENABLED"] == "false"
    assert env["VERIFUND_DATABASE_URL"].endswith("/verifund_smoke_test")
    assert env["VERIFUND_DATABASE_URL"].startswith("postgresql+psycopg://cp_app@")
    assert env["VERIFUND_AUTH_DATABASE_URL"].startswith("postgresql+psycopg://cp_auth@")
    assert env["VERIFUND_SERVICE_DATABASE_URL"].startswith("postgresql+psycopg://cp_service@")
    assert env["VERIFUND_DATABASE_URL_UNPOOLED"].startswith("postgresql+psycopg://cp_migrator@")
    assert env["VERIFUND_EVIDENCE_DIR"] == str(tmp_path / "evidence")
```

and remove the old `str(tmp_path / "verifund.db") in env["VERIFUND_DATABASE_URL"]`
assertion. Add `tests/unit/test_verifund_scripts.py` to the
`tests/unit/test_verifund_*.py` conversion sweep in Task 25 as well if it
creates any app fixture (it does not — only pure script functions).

- [ ] **Step 8: Update the packaging tests**

`tests/unit/test_verifund_packaging.py`:

- Replace the assertion
  `== "sqlite+aiosqlite:////app/data/verifund.db"` with a check that
  `VERIFUND_DATABASE_URL` starts with `postgresql+psycopg://cp_app` and that
  none of the four URLs contains `sqlite`.
- Add coverage for the one-shot services: `verifund-roles`,
  `verifund-migrate`, `verifund-seed` exist in compose and `verifund`
  `depends_on` includes `verifund-seed`.
- Keep the verifund-agent SQLite assertions unchanged (later plans).

`tests/unit/test_verifund_dev_config.py`:

- Replace any `verifund_database_url` expectation with `verifund_database_urls`
  returning the four URLs, and assert all four values start with
  `postgresql+psycopg://`.

- [ ] **Step 9: Update docs**

1. `README.md`:
   - Quick start: `docker compose up -d postgres` (or `make verifund-db-up`)
     before `make dev`, and note that the first run migrates and seeds the
     control-plane database.
   - Services table: control plane database = PostgreSQL 18.
2. `docs/architecture.md`: the Verifund control plane row/component
   description — replace `SQLite` with `PostgreSQL 18 (Neon)` and mention the
   request-scoped unit of work and RLS in one sentence.
3. `docs/verifund-paypal-sandbox.md`: replace the `VERIFUND_DATABASE_URL=sqlite...`
   block with the four URLs (pooled app URLs for `cp_app`/`cp_auth`/
   `cp_service`; direct migrator URL for `cp_migrator`), add a short
   "Provision the Neon database" section with the exact commands:
   ```bash
   uv run python scripts/provision_control_plane_roles.py --admin-url "$NEON_OWNER_URL" --database verifund_control_plane
   uv run alembic -c apps/verifund_control_plane/alembic.ini upgrade head
   uv run python scripts/seed_control_plane.py --database-url "$VERIFUND_SERVICE_DATABASE_URL"
   ```
   and note the smoke/test harness refuses non-`_test` database names.
4. `docs/runbook.md`: new section "Control plane on PostgreSQL":
   - local development (Compose; `make verifund-db-up`),
   - roles and grants (what `cp_migrator`, `cp_app`, `cp_auth`, `cp_service`
     may do; never use `neondb_owner` or `cp_migrator` at runtime),
   - provisioning a clean Neon project (empty schema; no migration of old
     SQLite rows),
   - migrations (deploy with `alembic upgrade head`; never `create_all`),
   - seeding (`scripts/seed_control_plane.py`; idempotent; system user
     `00000000-0000-0000-0000-000000000001`),
   - RLS summary and the checkpoint exception for buyer checkpoints,
   - credential rotation (rotate `neondb_owner` and the `.env` pooled owner
     URL; runtime uses role URLs),
   - rollback: revert the deployment; the Neon database keeps its schema.
5. `docs/architecture.md`/`docs/runbook.md`: state clearly that buyer,
   seller, registry, and agent databases remain on SQLite until plans 2–4
   land, and that local SQLite files are read-only legacy artifacts.

- [ ] **Step 10: Run the affected suites**

```bash
uv run pytest tests/unit/test_verifund_packaging.py tests/unit/test_verifund_dev_config.py tests/unit/test_verifund_scripts.py -q
docker compose config >/dev/null
```

Expected: 2 files pass; compose file validates.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: remove sqlite control-plane paths and update packaging"
```

---

### Task 29: Verify plan 1 end to end

**Files:**
- Modify: `docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md`
  (implementation-status notes only; do not change the design)
- Run: the full workspace check suite

- [ ] **Step 1: Static guarantees**

```bash
grep -rn 'python -m verifund_control_plane\|verifund_control_plane.db\|configure_sqlite\|create_schema' apps/verifund_control_plane tests/unit tests/integration scripts Makefile docker-compose.yml .env.example README.md docs
grep -rni 'sqlite' apps/verifund_control_plane scripts .env.example docker-compose.yml
grep -rn 'neondb_owner' . --exclude-dir=.git --exclude-dir=.venv
```

Expected: the first two commands print nothing (or only comments/docs that
state legacy status explicitly, which is acceptable in `docs/`). The owner
credential may appear only in `.env` as a documented-local secret with a
comment telling deployments not to use it; it must not appear in any committed
file.

- [ ] **Step 2: Lint**

```bash
uv run ruff check .
```

Expected: clean. Fix findings; do not loosen rule config.

- [ ] **Step 3: Full test suite**

```bash
docker compose up -d postgres
docker compose run --rm verifund-roles
docker compose run --rm verifund-migrate
docker compose run --rm verifund-seed
uv run pytest -q
```

Expected: the entire suite passes, including:

- every control-plane test (now on PostgreSQL),
- the role/RLS/matrix tests,
- the restart smoke test,
- all intentionally-unconverted buyer/seller/registry/agent/orchestrator
  suites running on SQLite as before.

If a test fails, `systematic-debugging` applies: identify whether the failure
is a conversion artifact (SQLite-era assumption about IDs, booleans, or
timestamps) and fix it at the source — never weaken a test to pass.

- [ ] **Step 4: Dependency check**

```bash
uv run python -c "import psycopg, alembic, langgraph_checkpoint_postgres; print(psycopg.__version__, alembic.__version__)"
```

Expected: psycopg 3.x, alembic 1.20+, no ImportError.

- [ ] **Step 5: Update the design doc's status table**

Add to `docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md`, under the Phase 0/1 exit criteria, a one-line note each:

- Phase 0 (foundation): **done** — plan 1 Tasks 1–8.
- Phase 1 (control plane): **done** — plan 1 Tasks 9–29; lifecycle smoke and
  restart persistence green; SQLite code removed.
- Phase 2 (buyer agent), Phase 3 (seller agents), Phase 4 (registry, Verifund
  agent, orchestrator): not started; see the plan index.
- Phase 5 (cutover): not started; Neon project is provisioned and empty of
  application data; local SQLite files are read-only legacy artifacts.

Do not change any design decision, table, or constraint in that document.

- [ ] **Step 6: Refresh the knowledge graph**

```bash
graphify update .
```

- [ ] **Step 7: Write the handoff**

Report, in this order:

1. What changed (one short paragraph), and where the verification evidence is
   (`pytest` output, RLS matrix, restart smoke).
2. The plan-1 exit criteria from the design doc and how each is met.
3. Known deviations and their rationale:
   - `/router` `/v1/agent-credentials/verify` is classified `service`
     (credential verification is a privileged service-to-service call with no
     tenant context).
   - Reconciler uses short per-record UoWs and idempotency/version guards;
     `SELECT ... FOR UPDATE SKIP LOCKED` claiming was not used because
     provider boundaries always release the transaction; flagged for review
     if multi-worker reconciliation is ever introduced.
   - `checkpoint()` exists only for handlers that persist state before
     returning an error response (provider-failure records, webhook events);
     normal 2xx paths commit via the middleware.
   - The webhook `/v1/webhooks/clerk` exception: no provider call, so the
     whole verify→record→apply step runs in the request UoW and rolls back
     atomically.
   - Buyer checkpoints remain on the app-level authorization exception;
     RLS applies to buyer data tables only (plans 2+).
4. What remains for the next plans: buyer agent (runs, settlement projections,
   A2A tasks, LangGraph `AsyncPostgresSaver`), seller agents + registry,
   Verifund agent + orchestrator session state, then Phase 5 cutover
   (Neon provisioning, deploy, smoke, rotation, restore rehearsal).
5. Operational notes: local Compose commands; `make verifund-db-up`; Neon
   is empty and ready; the `.env` owner credential must be rotated at cutover;
   local SQLite files stay untouched as read-only legacy.
6. The plan-1 commit list (`git log --oneline`) and the branch state.

Do not claim task completion until Step 3 has actually passed in this session.

---

## Plan Self-Review

Before marking plan 1 complete, check the plan against the design in
`docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md`:

- Every Phase 0 and Phase 1 item in design §10 is covered by a task.
- The "Plan 1: Foundation and Control Plane" scope boundary is respected: no
  buyer, seller, registry, verifund-agent, or orchestrator code changes.
- Each task has failing tests before implementation, an exact command to run,
  an expected failure, and a commit.
- No task leaves `app.py` creating SQLite engines, calling `create_schema()`,
  or calling the tenancy backfill.
- `checkpoint()` results: only the provider-failure and webhook-event paths
  use it; the design's "no transaction across provider calls" invariant holds
  everywhere else.
- Known deferred items are listed as deviations in Task 29 Step 7, not hidden.

If the self-review finds gaps, append or amend tasks before presenting plan 1
for execution.

