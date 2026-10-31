from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SellerCatalogProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    name: str
    category: str
    description: str = ""
    image_emoji: str = "📦"
    color: str = "#eef2ed"
    list_unit_price_cents: int | None = Field(default=None, gt=0)
    original_unit_price_cents: int | None = Field(default=None, gt=0)
    floor_unit_price_cents: int | None = Field(default=None, gt=0)
    initial_unit_price_cents: int | None = Field(default=None, gt=0)
    concession_ladder_cents: list[int] = Field(default_factory=list)
    base_warranty_months: int | None = Field(default=None, ge=0)
    warranty_addons_cents: dict[int, int] = Field(default_factory=dict)
    returns_days: int | None = Field(default=None, ge=0)
    delivery_days: int | None = Field(default=None, gt=0)
    stock_on_hand: int | None = Field(default=None, ge=0)
    incoming_stock: int | None = Field(default=None, ge=0)
    incoming_days: int | None = None
    split_shipment: bool | None = None
    sustainability_certified: bool | None = None
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    reviews: str = ""
    tag: str = "Available"
    color_name: str = "black"


class SellerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_id: str
    name: str
    tagline: str
    categories: list[str]
    list_unit_price_cents: int = Field(gt=0)
    floor_unit_price_cents: int = Field(gt=0)
    initial_unit_price_cents: int = Field(gt=0)
    concession_ladder_cents: list[int]
    base_warranty_months: int = Field(ge=0)
    warranty_addons_cents: dict[int, int]
    returns_days: int = Field(ge=0)
    delivery_days: int = Field(gt=0)
    stock_on_hand: int = Field(ge=0)
    incoming_stock: int = Field(default=0, ge=0)
    incoming_days: int | None = None
    split_shipment: bool = False
    sustainability_certified: bool
    rating: float = Field(ge=0.0, le=5.0)
    max_rounds: int = Field(default=3, ge=1)
    offer_ttl_minutes: int = Field(default=30, gt=0)
    color: str = "black"
    sku: str = "NC-700-BLK"
    product_name: str = "Nimbus NC-700 ANC Headset"
    products: list[SellerCatalogProduct] = Field(default_factory=list)
    mandate: dict | None = None
    def catalog(self) -> list[SellerCatalogProduct]:
        if self.products:
            return [
                product.model_copy(
                    update={
                        "category": product.category or self.categories[0],
                        "color_name": product.color_name or self.color,
                        "list_unit_price_cents": product.list_unit_price_cents or self.list_unit_price_cents,
                        "floor_unit_price_cents": product.floor_unit_price_cents or self.floor_unit_price_cents,
                        "initial_unit_price_cents": product.initial_unit_price_cents or self.initial_unit_price_cents,
                        "concession_ladder_cents": product.concession_ladder_cents or self.concession_ladder_cents,
                        "base_warranty_months": product.base_warranty_months if product.base_warranty_months is not None else self.base_warranty_months,
                        "warranty_addons_cents": product.warranty_addons_cents or self.warranty_addons_cents,
                        "returns_days": product.returns_days if product.returns_days is not None else self.returns_days,
                        "delivery_days": product.delivery_days or self.delivery_days,
                        "stock_on_hand": product.stock_on_hand if product.stock_on_hand is not None else self.stock_on_hand,
                        "incoming_stock": product.incoming_stock if product.incoming_stock is not None else self.incoming_stock,
                        "incoming_days": product.incoming_days if product.incoming_days is not None else self.incoming_days,
                        "split_shipment": product.split_shipment if product.split_shipment is not None else self.split_shipment,
                        "sustainability_certified": product.sustainability_certified if product.sustainability_certified is not None else self.sustainability_certified,
                        "rating": product.rating if product.rating is not None else self.rating,
                    }
                )
                for product in self.products
            ]
        return [
            SellerCatalogProduct(
                sku=self.sku,
                name=self.product_name,
                category=self.categories[0],
                color=self.color,
                list_unit_price_cents=self.list_unit_price_cents,
                floor_unit_price_cents=self.floor_unit_price_cents,
                initial_unit_price_cents=self.initial_unit_price_cents,
                concession_ladder_cents=self.concession_ladder_cents,
                base_warranty_months=self.base_warranty_months,
                warranty_addons_cents=self.warranty_addons_cents,
                returns_days=self.returns_days,
                delivery_days=self.delivery_days,
                stock_on_hand=self.stock_on_hand,
                incoming_stock=self.incoming_stock,
                incoming_days=self.incoming_days,
                split_shipment=self.split_shipment,
                sustainability_certified=self.sustainability_certified,
                rating=self.rating,
            )
        ]

    def for_product(self, sku: str | None = None, hint: str = "") -> SellerPolicy:
        catalog = self.catalog()
        product = next((item for item in catalog if sku and item.sku == sku), None)
        if sku and product is None:
            raise ValueError(f"unsupported product SKU: {sku}")
        if product is None and hint:
            normalized = hint.lower()
            product = next(
                (item for item in catalog if item.name.lower() in normalized), None
            )
            if product is None and any(term in normalized for term in ("nimbus", "headset")):
                product = next(
                    (item for item in catalog if "headphone" in item.name.lower()),
                    None,
                )
        if product is None:
            product = catalog[0]
        return self.model_copy(
            update={
                "sku": product.sku,
                "product_name": product.name,
                "categories": [product.category],
                "color": product.color_name,
                "list_unit_price_cents": product.list_unit_price_cents,
                "floor_unit_price_cents": product.floor_unit_price_cents,
                "initial_unit_price_cents": product.initial_unit_price_cents,
                "concession_ladder_cents": product.concession_ladder_cents,
                "base_warranty_months": product.base_warranty_months,
                "warranty_addons_cents": product.warranty_addons_cents,
                "returns_days": product.returns_days,
                "delivery_days": product.delivery_days,
                "stock_on_hand": product.stock_on_hand,
                "incoming_stock": product.incoming_stock,
                "incoming_days": product.incoming_days,
                "split_shipment": product.split_shipment,
                "sustainability_certified": product.sustainability_certified,
                "rating": product.rating,
            }
        )

    def next_price_options(self, previous_price_cents: int) -> list[int]:
        options: list[int] = []
        for price in self.concession_ladder_cents:
            if price < previous_price_cents and price not in options:
                options.append(price)
        return options or [previous_price_cents]

    def quote(
        self,
        quantity: int,
        unit_price_cents: int,
        warranty_months: int,
        allow_split: bool = False,
        stock_on_hand: int | None = None,
        incoming_stock: int | None = None,
        incoming_days: int | None = None,
    ) -> Quote:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if unit_price_cents < self.floor_unit_price_cents:
            raise ValueError("unit price is below floor")
        if unit_price_cents > self.list_unit_price_cents:
            raise ValueError("unit price exceeds list price")
        if warranty_months not in self.warranty_addons_cents:
            raise ValueError(f"unsupported warranty months: {warranty_months}")

        warranty_addon_cents = self.warranty_addons_cents[warranty_months]
        all_in_unit_price_cents = unit_price_cents + warranty_addon_cents
        subtotal_cents = all_in_unit_price_cents * quantity
        available_now = self.stock_on_hand if stock_on_hand is None else stock_on_hand
        arriving = self.incoming_stock if incoming_stock is None else incoming_stock
        arrival_days = self.incoming_days if incoming_days is None else incoming_days
        stock_confidence = (
            1.0
            if available_now >= quantity
            else available_now / quantity
        )
        split_shipment = bool(
            allow_split
            and available_now < quantity
            and available_now + arriving >= quantity
        )
        delivery_days = (
            arrival_days
            if split_shipment and arrival_days is not None
            else self.delivery_days
        )
        return Quote(
            base_unit_price_cents=unit_price_cents,
            warranty_addon_cents=warranty_addon_cents,
            unit_price_cents=all_in_unit_price_cents,
            subtotal_cents=subtotal_cents,
            total_cents=subtotal_cents,
            delivery_days=delivery_days,
            stock_confidence=stock_confidence,
            split_shipment=split_shipment,
            warranty_months=warranty_months,
            valid_until=datetime.now(UTC)
            + timedelta(minutes=self.offer_ttl_minutes),
        )

    def initial_quote(self, quantity: int) -> Quote:
        return self.quote(
            quantity=quantity,
            unit_price_cents=self.initial_unit_price_cents,
            warranty_months=self.base_warranty_months,
            allow_split=False,
        )


@dataclass(frozen=True)
class Quote:
    base_unit_price_cents: int
    warranty_addon_cents: int
    unit_price_cents: int
    subtotal_cents: int
    total_cents: int
    delivery_days: int
    stock_confidence: float
    split_shipment: bool
    warranty_months: int
    valid_until: datetime


def load_policy(path: str | Path) -> SellerPolicy:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return SellerPolicy.model_validate(data)


def counter_targets(
    initial_unit_price_cents: int,
    max_total_cents: int,
    quantity: int,
) -> list[int]:
    max_unit = max_total_cents // quantity
    targets = [
        int(initial_unit_price_cents * Decimal("0.97")),
        int(initial_unit_price_cents * Decimal("0.95")),
        int(initial_unit_price_cents * Decimal("0.93")),
    ]
    return [min(t, max_unit) for t in targets if 0 < t < initial_unit_price_cents]
