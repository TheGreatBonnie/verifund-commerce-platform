"""Discovery must never hide a registered seller behind a category naming difference."""
from __future__ import annotations

import pytest
from commerce_core.extension import EXTENSION_URI
from registry.store import RegistryStore
from sqlalchemy.ext.asyncio import create_async_engine

CARD_JSON = {
    "name": "Northwind Audio",
    "version": "1.0.0",
    "capabilities": {
        "streaming": True,
        "extensions": [{"uri": EXTENSION_URI, "required": True, "params": {}}],
    },
}


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    registry = RegistryStore(engine)
    await registry.create_schema()
    await registry.upsert(
        seller_id="northwind-audio",
        name="Northwind Audio",
        card_url="http://127.0.0.1:9201/.well-known/agent-card.json",
        categories=["Audio", "MacBook"],
        card_json=CARD_JSON,
        card_hash="hash-1",
        healthy=True,
        error=None,
    )
    await registry.upsert(
        seller_id="circuitforge",
        name="CircuitForge",
        card_url="http://127.0.0.1:9202/.well-known/agent-card.json",
        categories=["Keyboard"],
        card_json=CARD_JSON,
        card_hash="hash-2",
        healthy=True,
        error=None,
    )
    await registry.replace_listings(
        "circuitforge",
        [{"sku": "KB-1", "name": "Keyboard", "category": "Keyboard"}],
    )
    yield registry
    await engine.dispose()


async def test_discover_narrows_to_the_sellers_indexed_under_a_known_category(store):
    found = await store.discover("Audio", EXTENSION_URI)

    assert [row["seller_id"] for row in found] == ["northwind-audio"]


async def test_discover_matches_a_known_category_case_insensitively(store):
    found = await store.discover("audio", EXTENSION_URI)

    assert [row["seller_id"] for row in found] == ["northwind-audio"]


async def test_discover_does_not_hide_sellers_behind_an_unknown_category(store):
    found = await store.discover("consumer-electronics", EXTENSION_URI)

    assert sorted(row["seller_id"] for row in found) == [
        "circuitforge",
        "northwind-audio",
    ]


async def test_discover_ignores_an_empty_category(store):
    found = await store.discover("", EXTENSION_URI)

    assert sorted(row["seller_id"] for row in found) == [
        "circuitforge",
        "northwind-audio",
    ]


async def test_a_product_sku_identifies_the_seller_without_a_category_match(store):
    """The SKU names the product, so it decides who is asked — not the category."""
    found = await store.discover("Audio", EXTENSION_URI, product_sku="KB-1")

    assert [row["seller_id"] for row in found] == ["circuitforge"]
