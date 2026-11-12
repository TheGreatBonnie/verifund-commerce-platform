"""Failing-first tests for image_url replacement (full-stack).

RED: these fail because SellerCatalogProduct/pricing, template
and offer attributes still use image_emoji/color.
"""

from pathlib import Path

from commerce_core.pricing import SellerCatalogProduct, load_policy


def test_catalog_product_accepts_image_url():
    product = SellerCatalogProduct(
        sku="EX-LAPTOP-M4",
        name="ExamplePro 14 Laptop",
        category="Electronics",
        description="14-inch laptop",
        list_unit_price_cents=149900,
        initial_unit_price_cents=139900,
        floor_unit_price_cents=129900,
        image_url="https://images.unsplash.com/photo-x?w=500",
        rating=4.6,
        reviews="230",
        tag="Popular",
    )
    assert product.image_url == "https://images.unsplash.com/photo-x?w=500"
    assert not hasattr(product, "image_emoji")
    assert not hasattr(product, "color")


def test_template_uses_image_url_not_emoji_color():
    template = Path("apps/console/public/example-catalog-template.yaml").read_text()
    assert "image_url" in template
    assert "image_emoji" not in template
    assert "color:" not in template


def test_policy_catalog_propagates_image_url():
    from seller_agent.catalog_import import parse_catalog_document

    raw = Path("scripts/fixtures/example-catalog.yaml").read_text()
    catalog = parse_catalog_document(raw)
    assert catalog[0].image_url.startswith("https://")
    assert not hasattr(catalog[0], "image_emoji")
