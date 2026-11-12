"""Seed seller catalogs, control-plane agents, and register Agent Cards."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from commerce_core.pricing import load_policy
from config import (
    ROOT,
    admin_token,
    registry_url,
    shared_seller_db_url,
    shared_seller_url,
    verifund_database_url,
)

SEED_SELLERS = (
    SimpleNamespace(
        seller_id="northwind-audio",
        profile="northwind.yaml",
        token="dev-northwind",
        profile_path=ROOT / "docs/templates" / "northwind.yaml",
    ),
    SimpleNamespace(
        seller_id="circuitforge",
        profile="circuitforge.yaml",
        token="dev-circuitforge",
        profile_path=ROOT / "docs/templates" / "circuitforge.yaml",
    ),
    SimpleNamespace(
        seller_id="aurora-supply",
        profile="aurora.yaml",
        token="dev-aurora",
        profile_path=ROOT / "docs/templates" / "aurora.yaml",
    ),
    SimpleNamespace(
        seller_id="summit-tech",
        profile="summit-tech.yaml",
        token="dev-summit-tech",
        profile_path=ROOT / "docs/templates" / "summit-tech.yaml",
    ),
)
try:
    from .seed_shared import seed_seller_rows
except ImportError:
    from seed_shared import seed_seller_rows
from seller_agent.shared_schema import (
    configure_shared_engine,
    create_shared_schema,
)
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.tenancy.backfill import seed_demo_agents
from verifund_control_plane.tenancy.repository import TenancyRepository

BUYER_AGENT_ID = "agent_marketmesh_buyer"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def seed_control_plane() -> tuple[dict[str, str], dict]:
    engine = create_async_engine(verifund_database_url())
    repo = TenancyRepository(engine)
    try:
        await repo.create_schema()
        demo = SimpleNamespace()
        await seed_demo_agents(repo, demo)
        organizations: dict[str, str] = {}
        for seller in SEED_SELLERS:
            profile = await repo.get_seller_profile(seller.seller_id)
            if profile is not None:
                organizations[seller.seller_id] = profile["organization_id"]
        buyer = await repo.get_agent(BUYER_AGENT_ID)
        return organizations, buyer or {}
    finally:
        await engine.dispose()


async def seed_catalogs(organizations: dict[str, str]) -> list[tuple[str, int]]:
    engine = create_async_engine(shared_seller_db_url())
    seeded: list[tuple[str, int]] = []
    try:
        await configure_shared_engine(engine)
        await create_shared_schema(engine)
        for seller in SEED_SELLERS:
            organization_id = organizations.get(seller.seller_id)
            if not organization_id:
                print(
                    f"skipping {seller.seller_id}: no control-plane organization",
                    file=sys.stderr,
                )
                continue
            count = await seed_seller_rows(
                engine,
                seller_id=seller.seller_id,
                agent_id=f"agent_{seller.seller_id}",
                organization_id=organization_id,
                profile_path=seller.profile_path,
                public_base_url=shared_seller_url(),
            )
            seeded.append((seller.seller_id, count))
    finally:
        await engine.dispose()
    return seeded


def write_demo_credentials(
    organizations: dict[str, str], buyer: dict
) -> Path:
    path = Path("data/demo-credentials.json")
    tokens = {}
    # Demo-credentials file is used only by VERIFUND_MODE=off verifier.
    # Tokens here are locally generated, unique per seed run, and keyed by
    # hash in this file. Dynamic modes (sandbox/fake) mint credentials via
    # the control plane instead.
    import secrets as _secrets

    if buyer:
        buyer_token = "vf_agent_" + _secrets.token_urlsafe(32)
        tokens[_hash(buyer_token)] = {
            "organization_id": buyer["organization_id"],
            "agent_id": BUYER_AGENT_ID,
            "status": "active",
            "scopes": ["a2a:call"],
        }
    for seller in SEED_SELLERS:
        organization_id = organizations.get(seller.seller_id)
        if not organization_id:
            continue
        tokens[_hash(seller.token)] = {
            "organization_id": organization_id,
            "agent_id": f"agent_{seller.seller_id}",
            "status": "active",
            "scopes": ["a2a:test"],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tokens": tokens}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def register_seller(
    client: httpx.Client, config, *, registry: str, token: str
) -> dict:
    policy = load_policy(config.profile_path)
    card_url = (
        f"{shared_seller_url()}/{config.seller_id}"
        "/.well-known/agent-card.json"
    )
    response = client.post(
        f"{registry}/v1/sellers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "seller_id": config.seller_id,
            "card_url": card_url,
            "categories": sorted(
                set(policy.categories)
                | {product.category for product in policy.catalog()}
            ),
        },
    )
    response.raise_for_status()
    return response.json()


async def main() -> int:
    registry = registry_url().rstrip("/")
    token = admin_token()

    organizations, buyer = await seed_control_plane()
    seeded = await seed_catalogs(organizations)
    for seller_id, stock in seeded:
        print(f"seeded {seller_id}: {stock} catalog items")
    credentials = write_demo_credentials(organizations, buyer)
    print(f"wrote demo credentials -> {credentials}")

    try:
        with httpx.Client(timeout=20.0) as client:
            for seller in SEED_SELLERS:
                row = register_seller(
                    client,
                    seller,
                    registry=registry,
                    token=token,
                )
                print(
                    f"registered {row['seller_id']} -> {row['card_url']}"
                )
    except httpx.HTTPError as exc:
        print(
            f"Registry is not available at {registry}: {exc}\n"
            "Start the registry and sellers before seeding "
            "(run `make dev` first, then `make seed-demo`).",
            file=sys.stderr,
        )
        return 1

    print(f"seed complete: {len(seeded)} sellers, data under {ROOT / 'data'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
