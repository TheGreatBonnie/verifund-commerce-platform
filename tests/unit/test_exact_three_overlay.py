"""Failing-first for exact-3 rule-of-thumb overlay.

RED: fails because current seller catalogs vary only money/stock/tag,
not warranty/returns/delivery/sustainability/color_name, and identity check
needs pinning.
"""
from collections import defaultdict
import yaml
from pathlib import Path

SELLERS = ["northwind", "circuitforge", "aurora", "summit-tech"]
IDENTITY = ["name", "description", "category", "image_url"]
OVERLAY = [
    "list_unit_price_cents",
    "tag",
    "delivery_days",
    "returns_days",
    "base_warranty_months",
    "color_name",
    "stock_on_hand",
]
# sustainability_certified is boolean: cannot be 3 distinct values; check >=2 diversity separately


def _load(seller):
    return yaml.safe_load(Path(f"docs/templates/{seller}.yaml").read_text())["products"]


def test_exactly_three_per_sku_and_identity_identical():
    mapping = defaultdict(list)
    for seller in SELLERS:
        for p in _load(seller):
            mapping[p["sku"]].append(p)
    assert len(mapping) == 60
    for sku, copies in mapping.items():
        assert len(copies) == 3, f"{sku} in {len(copies)} sellers"
        for field in IDENTITY:
            assert len({c[field] for c in copies}) == 1, f"{sku} identity {field} varies"


def test_overlay_fields_vary_per_seller():
    mapping = defaultdict(list)
    for seller in SELLERS:
        for p in _load(seller):
            mapping[p["sku"]].append(p)
    for sku, copies in mapping.items():
        for field in OVERLAY:
            values = {str(c.get(field)) for c in copies}
            assert len(values) == len(copies), f"{sku} overlay {field} not fully varying: {values}"
        # sustainability boolean must show both true/false across the 3 copies
        assert len({c.get("sustainability_certified") for c in copies}) >= 2, sku
