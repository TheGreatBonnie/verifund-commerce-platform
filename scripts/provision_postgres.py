"""Create one database per service inside a single Postgres instance.

Render's free tier allows one Postgres instance, so every service gets its own
database inside it. This script is idempotent: existing databases are skipped.

Usage:

    uv run python scripts/provision_postgres.py \
        --base-url "postgresql://marketmesh:pw@dpg-xxxx.oregon-postgres.render.com/marketmesh"

The base URL's credentials are reused for every service database. Pass
``--show-passwords`` to print the full connection URLs to paste into Render.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

# Service database name -> environment variable that receives its URL.
SERVICE_ENV_VARS: dict[str, str] = {
    "buyer": "BUYER_DATABASE_URL",
    "registry": "REGISTRY_DATABASE_URL",
    "sellers": "SELLER_SHARED_DB_URL",
    "verifund": "VERIFUND_DATABASE_URL",
    "verifund_agent": "VERIFUND_AGENT_DATABASE_URL",
    "orchestrator": "ORCHESTRATOR_SESSION_DB_URL",
}

CHECKPOINT_ENV_VARS: dict[str, str] = {
    "buyer": "BUYER_CHECKPOINT_URL",
    "sellers": "SELLER_CHECKPOINT_URL",
    "verifund_agent": "VERIFUND_AGENT_CHECKPOINT_URL",
}

DEFAULT_DATABASES: tuple[str, ...] = tuple(SERVICE_ENV_VARS)


def libpq_dsn(base_url: str) -> str:
    """Strip the SQLAlchemy driver suffix so psycopg can parse the URL."""

    url = make_url(base_url)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def service_database_url(base_url: str, database: str) -> str:
    """Return a SQLAlchemy URL for ``database`` on the same server."""

    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError(f"not a PostgreSQL URL: {base_url}")
    return url.set(drivername="postgresql+psycopg", database=database).render_as_string(
        hide_password=False
    )


def redact(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def existing_databases(conn: Any) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT datname FROM pg_database")
        return {str(row[0]) for row in cursor.fetchall()}


def missing_databases(conn: Any, databases: Iterable[str]) -> list[str]:
    present = existing_databases(conn)
    return [name for name in databases if name not in present]


def provision(base_url: str, databases: Sequence[str]) -> list[str]:
    """Create the missing databases and return the ones that were created."""

    created: list[str] = []
    with psycopg.connect(libpq_dsn(base_url), autocommit=True) as conn:
        for name in missing_databases(conn, databases):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created.append(name)
    return created


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Postgres URL to the instance")
    parser.add_argument(
        "--databases",
        nargs="*",
        default=list(DEFAULT_DATABASES),
        help="Database names to create (defaults to one per service)",
    )
    parser.add_argument(
        "--show-passwords",
        action="store_true",
        help="Print full connection URLs instead of redacted ones",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        created = provision(args.base_url, args.databases)
    except (ValueError, psycopg.Error) as exc:
        print(f"provisioning failed: {exc}", file=sys.stderr)
        return 1

    if created:
        print("created: " + ", ".join(created))
    else:
        print("all databases already present")

    print("\nEnvironment values:")
    for name in args.databases:
        url = service_database_url(args.base_url, name)
        shown = url if args.show_passwords else redact(url)
        env_var = SERVICE_ENV_VARS.get(name)
        if env_var:
            print(f"  {env_var}={shown}")
    for name, env_var in CHECKPOINT_ENV_VARS.items():
        if name in args.databases:
            url = service_database_url(args.base_url, name)
            shown = url if args.show_passwords else redact(url)
            print(f"  {env_var}={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CHECKPOINT_ENV_VARS",
    "DEFAULT_DATABASES",
    "SERVICE_ENV_VARS",
    "existing_databases",
    "libpq_dsn",
    "main",
    "missing_databases",
    "provision",
    "redact",
    "service_database_url",
]
