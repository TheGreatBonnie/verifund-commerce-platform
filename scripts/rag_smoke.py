"""Manual pure-RAG smoke run against the seeded seller templates.

Usage:
    NEBIUS_API_KEY=... uv run python scripts/rag_smoke.py

Requires network access to the Nebius Token Factory embeddings endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from commerce_core.pricing import load_policy
from commerce_core.retrieval import NebiusEmbeddings, ProductRetriever
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "docs" / "templates"
load_dotenv(ROOT / ".env")

MODEL = os.environ.get("NEBIUS_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
DIMENSIONS = 1024

QUERIES: list[dict] = [
    {"query": "good laptop for programming under $1500", "max_unit_price_cents": 150000},
    {"query": "noise cancelling headphones for travel"},
    {"query": "standing desk for a small home office", "category": "Standing Desk"},
    {"query": "zzzzzz"},
]


def build_catalog() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(TEMPLATES.glob("*.yaml")):
        policy = load_policy(path)
        for item in policy.catalog():
            price = (
                item.initial_unit_price_cents
                or item.list_unit_price_cents
                or policy.list_unit_price_cents
            )
            rows.append(
                {
                    "id": item.sku,
                    "sku": item.sku,
                    "name": item.name,
                    "category": item.category,
                    "description": item.description,
                    "rating": item.rating,
                    "original_unit_price_cents": item.original_unit_price_cents,
                    "unit_price_cents": price,
                    "offers": [
                        {
                            "seller_id": policy.seller_id,
                            "seller_name": policy.name,
                            "unit_price_cents": price,
                            "currency": "USD",
                            "available": bool(item.stock_on_hand),
                            "on_hand": item.stock_on_hand or 0,
                            "incoming": item.incoming_stock or 0,
                        }
                    ],
                }
            )
    return rows


def main() -> None:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise SystemExit("NEBIUS_API_KEY is required for the smoke run")

    catalog = build_catalog()
    retriever = ProductRetriever(
        NebiusEmbeddings(
            api_key=api_key,
            base_url=os.environ.get("NEBIUS_EMBEDDING_BASE_URL")
            or os.environ.get("NEBIUS_BASE_URL")
            or "https://api.tokenfactory.us-central1.nebius.com/v1/",
            model=MODEL,
            dimensions=DIMENSIONS,
        ),
        model=MODEL,
        dimensions=DIMENSIONS,
    )

    print(f"catalog: {len(catalog)} products")
    for spec in QUERIES:
        result = retriever.search(catalog, **spec)
        print(f"\nquery: {spec}")
        print(f"trace: {result.trace}")
        for product in result.products[:10]:
            reason = (product.get("match_rationale") or ["-"])[0]
            print(
                f"  {product['sku']:<24} "
                f"{product['unit_price_cents']:>8}c  {reason:<16} {product['name']}"
            )


if __name__ == "__main__":
    main()
