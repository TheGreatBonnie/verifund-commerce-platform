"""Seed seller catalogs and register all Agent Cards with the registry."""

from __future__ import annotations

import asyncio
import sys

import httpx
from commerce_core.pricing import load_policy
from config import (
    ROOT,
    SELLERS,
    admin_token,
    registry_url,
)
from seller_agent.store import SellerStore
from sqlalchemy.ext.asyncio import create_async_engine


async def seed_seller(config) -> tuple[str, int]:
    policy = load_policy(config.profile_path)
    engine = create_async_engine(config.database_url)
    store = SellerStore(engine)
    try:
        await store.create_schema()
        for product in policy.catalog():
            await store.set_stock(
                product.sku,
                product.stock_on_hand or 0,
                product.incoming_stock or 0,
                product.incoming_days,
            )
    finally:
        await engine.dispose()
    return policy.seller_id, len(policy.catalog())


def register_seller(
    client: httpx.Client, config, *, registry: str, token: str
) -> dict:
    response = client.post(
        f"{registry}/v1/sellers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "seller_id": config.seller_id,
            "card_url": config.card_url,
            "categories": sorted(
                set(load_policy(config.profile_path).categories)
                | {product.category for product in load_policy(config.profile_path).catalog()}
            ),
        },
    )
    response.raise_for_status()
    return response.json()


async def main() -> int:
    registry = registry_url().rstrip("/")
    token = admin_token()

    seeded = []
    for seller in SELLERS:
        seller_id, stock = await seed_seller(seller)
        seeded.append((seller_id, stock))
        print(f"seeded {seller_id}: {stock} catalog items")

    try:
        with httpx.Client(timeout=20.0) as client:
            for seller in SELLERS:
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
            "(or run `make dev`, which seeds automatically).",
            file=sys.stderr,
        )
        return 1

    print(f"seed complete: {len(seeded)} sellers, data under {ROOT / 'data'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
