from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


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
    ) -> "Quote":
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
        stock_confidence = (
            1.0
            if self.stock_on_hand >= quantity
            else self.stock_on_hand / quantity
        )
        split_shipment = bool(
            allow_split
            and self.stock_on_hand < quantity
            and self.stock_on_hand + self.incoming_stock >= quantity
        )
        delivery_days = (
            self.incoming_days
            if split_shipment and self.incoming_days is not None
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

    def initial_quote(self, quantity: int) -> "Quote":
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
