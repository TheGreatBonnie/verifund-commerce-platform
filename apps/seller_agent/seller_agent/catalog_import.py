from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_PRODUCTS = 1000


class ImportErrorEntry(BaseModel):
    row: int | None = None
    field: str | None = None
    message: str


class CatalogImportError(Exception):
    def __init__(self, errors: list[ImportErrorEntry]) -> None:
        super().__init__("catalog import failed")
        self.errors = [e.model_dump(exclude_none=True) for e in errors]


class ImportProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    description: str = ""
    list_unit_price_cents: int = Field(gt=0)
    original_unit_price_cents: int | None = Field(default=None, gt=0)
    initial_unit_price_cents: int = Field(gt=0)
    floor_unit_price_cents: int = Field(gt=0)
    concession_ladder_cents: list[int] = Field(default_factory=list)
    warranty_addons_cents: dict[int, int] = Field(default_factory=dict)
    base_warranty_months: int = Field(default=12, ge=0)
    returns_days: int = Field(default=30, ge=0)
    delivery_days: int = Field(default=5, gt=0)
    stock_on_hand: int = Field(default=0, ge=0)
    incoming_stock: int = Field(default=0, ge=0)
    incoming_days: int | None = None
    image_emoji: str = "📦"
    color: str = "#eef2ed"
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    reviews: str = ""
    tag: str = ""
    color_name: str = "black"
    sustainability_certified: bool | None = None

    @model_validator(mode="after")
    def _ordering(self):
        if not (self.floor_unit_price_cents <= self.initial_unit_price_cents
                <= self.list_unit_price_cents):
            raise ValueError(
                "floor_unit_price_cents <= initial_unit_price_cents "
                "<= list_unit_price_cents")
        for v in self.concession_ladder_cents:
            if not (self.floor_unit_price_cents <= v <= self.list_unit_price_cents):
                raise ValueError("concession_ladder_cents values out of bounds")
        return self


def _sniff(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise CatalogImportError(
            [ImportErrorEntry(message=f"document is neither JSON nor YAML: {e}")])


def parse_catalog_document(content: str) -> list[ImportProduct]:
    if len(content.encode("utf-8", errors="ignore")) > MAX_IMPORT_BYTES:
        raise CatalogImportError([ImportErrorEntry(message="document exceeds 2 MB")])
    doc = _sniff(content)
    if not isinstance(doc, dict):
        raise CatalogImportError(
            [ImportErrorEntry(message="top-level document must be an object")])
    raw_products = doc.get("products")
    if not isinstance(raw_products, list):
        raise CatalogImportError(
            [ImportErrorEntry(field="products", message="products must be a list")])
    if len(raw_products) > MAX_PRODUCTS:
        raise CatalogImportError(
            [ImportErrorEntry(field="products",
                              message=f"more than {MAX_PRODUCTS} products")])
    if len(raw_products) == 0:
        raise CatalogImportError(
            [ImportErrorEntry(field="products", message="at least one product is required")])
    errors: list[ImportErrorEntry] = []
    products: list[ImportProduct] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_products):
        if not isinstance(raw, dict):
            errors.append(ImportErrorEntry(
                row=index + 1, message="product must be an object"))
            continue
        try:
            product = ImportProduct.model_validate(raw)
        except Exception as e:
            msg = " ".join(str(e).splitlines())[:400]
            errors.append(ImportErrorEntry(row=index + 1, message=msg))
            continue
        if product.sku in seen:
            errors.append(ImportErrorEntry(
                row=index + 1, field="sku",
                message=f"duplicate sku {product.sku}"))
        seen.add(product.sku)
        products.append(product)
    if errors:
        raise CatalogImportError(errors)
    return products
