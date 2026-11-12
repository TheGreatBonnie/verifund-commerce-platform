"""Turn marketplace product rows into embeddable documents."""

from __future__ import annotations

from langchain_core.documents import Document

from .filters import offer_available, price_cents, seller_name


def product_document(product: dict) -> Document:
    sku = str(product.get("sku") or "")
    name = str(product.get("name") or "")
    category = str(product.get("category") or "")
    description = str(product.get("description") or "")
    seller = seller_name(product)

    lines = [value for value in (name, category, sku, description) if value]
    if seller:
        lines.append(f"Seller: {seller}")

    rating = product.get("rating")
    metadata = {
        "sku": sku,
        "name": name,
        "category": category,
        "price_cents": price_cents(product),
        "available": offer_available(product),
        "rating": rating if isinstance(rating, (int, float)) else None,
    }
    return Document(id=sku or None, page_content="\n".join(lines), metadata=metadata)
