from __future__ import annotations

from commerce_core.retrieval.documents import product_document

PRODUCT = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 - 16GB memory - 256GB SSD - Space Gray",
    "unit_price_cents": 99900,
    "original_unit_price_cents": 119900,
    "rating": 4.6,
    "offers": [
        {
            "seller_name": "Northwind Audio",
            "unit_price_cents": 99900,
            "currency": "USD",
            "available": True,
            "on_hand": 8,
        }
    ],
}


def test_embedded_text_contains_every_semantic_field():
    document = product_document(PRODUCT)

    assert "MacBook Air M4 13-inch" in document.page_content
    assert "Electronics" in document.page_content
    assert "MM-MACBOOK-AIR-M4-13" in document.page_content
    assert "16GB memory" in document.page_content
    assert "Seller: Northwind Audio" in document.page_content


def test_embedded_text_excludes_price_and_availability():
    document = product_document(PRODUCT).page_content.casefold()

    assert "99900" not in document
    assert "119900" not in document
    assert "price" not in document
    assert "stock" not in document
    assert "available" not in document


def test_metadata_carries_filter_and_rationale_fields():
    document = product_document(PRODUCT)

    assert document.metadata == {
        "sku": "MM-MACBOOK-AIR-M4-13",
        "name": "MacBook Air M4 13-inch",
        "category": "Electronics",
        "price_cents": 99900,
        "available": True,
        "rating": 4.6,
    }
    assert document.id == "MM-MACBOOK-AIR-M4-13"


def test_sparse_rows_do_not_produce_blank_lines():
    document = product_document({"sku": "SKU-1", "name": "Widget"})

    assert document.page_content == "Widget\nSKU-1"
    assert document.metadata["available"] is False
    assert document.metadata["price_cents"] == 0


def test_documents_are_deterministic():
    assert product_document(PRODUCT).page_content == product_document(PRODUCT).page_content
