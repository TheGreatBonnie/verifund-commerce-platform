from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Currency(StrEnum):
    USD = "USD"


class OfferStatus(StrEnum):
    PROPOSED = "proposed"
    FINAL = "final"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CommerceErrorCode(StrEnum):
    OUT_OF_STOCK = "out_of_stock"
    OFFER_EXPIRED = "offer_expired"
    BELOW_FLOOR = "below_floor"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CONSTRAINT = "unsupported_constraint"
    CONFLICT = "conflict"


class CommerceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Preferences(CommerceModel):
    sustainability: bool = False
    color: str | None = None


class Mandate(CommerceModel):
    run_id: str
    buyer_id: str = "demo-buyer"
    category: str
    product_hint: str
    product_sku: str | None = None
    quantity: int = Field(gt=0)
    max_total_cents: int = Field(gt=0)
    deadline_days: int = Field(gt=0)
    min_warranty_months: int = Field(ge=0)
    min_returns_days: int = Field(ge=0)
    preferences: Preferences = Field(default_factory=Preferences)
    currency: Currency = Currency.USD
    approval_required: bool = True


ShoppingBrief = Mandate


class RFQConstraints(CommerceModel):
    min_warranty_months: int = Field(default=0, ge=0)
    min_returns_days: int = Field(default=0, ge=0)
    color: str | None = None


class RFQPreferences(CommerceModel):
    sustainability: bool = False
    delivery_preference: str | None = None


class RFQ(CommerceModel):
    schema_version: str = "1.0"
    request_id: str
    run_id: str
    category: str
    product_hint: str
    product_sku: str | None = None
    quantity: int = Field(gt=0)
    required_by: datetime
    constraints: RFQConstraints = Field(default_factory=RFQConstraints)
    preferences: RFQPreferences = Field(default_factory=RFQPreferences)
    message: str | None = None


class OfferLineItem(CommerceModel):
    sku: str
    name: str
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(gt=0)
    list_unit_price_cents: int = Field(gt=0)
    warranty_addon_cents: int = Field(default=0, ge=0)
    attributes: dict[str, str] = Field(default_factory=dict)


class OfferTerms(CommerceModel):
    sustainability_certified: bool = False
    stock_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    split_shipment: bool = False
    notes: str | None = None


class Offer(CommerceModel):
    offer_id: str
    request_id: str
    seller_id: str
    seller_name: str
    seller_rating: float = Field(ge=0.0, le=5.0)
    task_id: str | None = None
    context_id: str | None = None
    currency: Currency = Currency.USD
    line_items: list[OfferLineItem]
    subtotal_cents: int = Field(ge=0)
    shipping_cents: int = Field(default=0, ge=0)
    tax_cents: int = Field(default=0, ge=0)
    fees_cents: int = Field(default=0, ge=0)
    total_cents: int = Field(ge=0)
    delivery_days: int = Field(gt=0)
    delivery_date: datetime | None = None
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    valid_until: datetime
    terms: OfferTerms = Field(default_factory=OfferTerms)
    status: OfferStatus = OfferStatus.PROPOSED
    round: int = Field(default=1, ge=1)
    binding_version: int = Field(default=1, ge=1)
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_totals(self) -> Offer:
        computed = 0
        for item in self.line_items:
            if item.quantity <= 0:
                raise ValueError("line item quantity must be positive")
            if item.unit_price_cents <= 0:
                raise ValueError("line item unit price must be positive")
            if item.warranty_addon_cents < 0:
                raise ValueError("warranty add-on must not be negative")
            computed += (
                item.unit_price_cents + item.warranty_addon_cents
            ) * item.quantity
        if computed != self.subtotal_cents:
            raise ValueError("subtotal_cents does not match line items")
        if self.total_cents != (
            self.subtotal_cents + self.shipping_cents
            + self.tax_cents + self.fees_cents
        ):
            raise ValueError("total_cents does not match subtotal, shipping, tax, fees")
        if self.delivery_days <= 0:
            raise ValueError("delivery_days must be positive")
        return self


class CounterOffer(CommerceModel):
    schema_version: str = "1.0"
    negotiation_round: int = Field(ge=1)
    target_unit_price_cents: int | None = Field(default=None, gt=0)
    requested_changes: dict[str, str | int | bool] = Field(default_factory=dict)
    rationale: str = ""


class AcceptOffer(CommerceModel):
    schema_version: str = "1.0"
    offer_id: str
    round: int = Field(ge=1)
    accepted_total_cents: int = Field(gt=0)
    accepted_by_buyer_task: str | None = None
    settlement_transaction_id: str | None = None
    agreement_hash: str | None = None
    settlement_token: str | None = None


class ApprovalReceipt(CommerceModel):
    approval_id: str
    approved_by: str
    approved_at: datetime
    note: str | None = None


class ShippingAddress(CommerceModel):
    name: str
    line1: str
    city: str
    region: str
    postal_code: str
    country: str


class PurchaseOrderRequest(CommerceModel):
    schema_version: str = "1.0"
    request_id: str
    run_id: str
    offer_id: str
    seller_id: str
    quantity: int = Field(gt=0)
    shipping_address: ShippingAddress
    approval: ApprovalReceipt
    idempotency_key: str
    expected_total_cents: int = Field(gt=0)
    settlement_transaction_id: str | None = None
    agreement_hash: str | None = None
    settlement_token: str | None = None


class Fulfillment(CommerceModel):
    carrier: str
    status: str


class Order(CommerceModel):
    schema_version: str = "1.0"
    order_id: str
    offer_id: str
    seller_id: str
    status: OrderStatus = OrderStatus.CONFIRMED
    currency: Currency = Currency.USD
    quantity: int = Field(gt=0)
    total_cents: int = Field(ge=0)
    line_items: list[OfferLineItem]
    reserved_at: datetime
    eta: datetime
    tracking_number: str
    fulfillment: Fulfillment


class CommerceError(CommerceModel):
    code: CommerceErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class NegotiationRecord(CommerceModel):
    seller_id: str
    seller_name: str
    task_id: str
    status: str
    rounds: list[Offer] = Field(default_factory=list)
    final_offer: Offer | None = None
    error: str | None = None


class AwardPackage(CommerceModel):
    winner: Offer
    score: float
    alternatives: list[Offer] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    savings_cents: int = 0
    mandate_checks: list[str] = Field(default_factory=list)
