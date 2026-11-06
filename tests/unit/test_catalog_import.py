import json
from pathlib import Path

import pytest
import yaml

from seller_agent.catalog_import import parse_catalog_document, CatalogImportError

GOOD = json.dumps({"version": 1, "currency": "USD", "products": [
    {"sku": "S1", "name": "One", "category": "c", "list_unit_price_cents": 100,
     "initial_unit_price_cents": 90, "floor_unit_price_cents": 80, "stock_on_hand": 1},
]})


def test_parses_json():
    products = parse_catalog_document(GOOD)
    assert products[0].sku == "S1"


def test_parses_yaml():
    products = parse_catalog_document(yaml.safe_dump(json.loads(GOOD)))
    assert products[0].sku == "S1"


def test_rejects_floor_above_initial():
    bad = json.dumps({"version": 1, "products": [
        {"sku": "S1", "name": "One", "category": "c", "list_unit_price_cents": 100,
         "initial_unit_price_cents": 70, "floor_unit_price_cents": 80, "stock_on_hand": 1},
    ]})
    with pytest.raises(CatalogImportError) as exc:
        parse_catalog_document(bad)
    assert any("floor_unit_price_cents" in e["message"] or e["field"] == "initial_unit_price_cents"
               for e in exc.value.errors)


def test_rejects_duplicate_sku():
    dup = json.loads(GOOD)
    dup["products"].append(dup["products"][0])
    with pytest.raises(CatalogImportError) as exc:
        parse_catalog_document(json.dumps(dup))
    assert any("duplicate" in e["message"].lower() for e in exc.value.errors)


def test_rejects_unknown_field():
    bad = json.loads(GOOD)
    bad["products"][0]["wat"] = 1
    with pytest.raises(CatalogImportError):
        parse_catalog_document(json.dumps(bad))


def test_size_cap():
    with pytest.raises(CatalogImportError):
        parse_catalog_document("x" * (2 * 1024 * 1024 + 1))


def test_product_cap():
    many = {"version": 1, "products": [
        {"sku": f"S{i}", "name": "n", "category": "c", "list_unit_price_cents": 100,
         "initial_unit_price_cents": 90, "floor_unit_price_cents": 80, "stock_on_hand": 0}
        for i in range(1001)
    ]}
    with pytest.raises(CatalogImportError):
        parse_catalog_document(json.dumps(many))


def test_example_assets_are_valid():
    fixture = Path("scripts/fixtures/example-catalog.json").read_text()
    assert parse_catalog_document(fixture)
    fixture_yaml = Path("scripts/fixtures/example-catalog.yaml").read_text()
    assert parse_catalog_document(fixture_yaml)


def test_no_writes_on_failure_contract():
    # parse raises before the caller performs any writes
    bad = json.dumps({"version": 1, "products": [
        {"sku": "S1", "name": "One", "category": "c",
         "initial_unit_price_cents": 90, "floor_unit_price_cents": 80},
    ]})
    with pytest.raises(CatalogImportError):
        parse_catalog_document(bad)
