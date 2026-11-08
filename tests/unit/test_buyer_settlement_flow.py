from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from buyer_agent.settlement_flow import (
    build_award_request,
    create_award,
    report_acceptance,
    report_purchase_order,
    settlement_enabled,
    start_funding,
)
from commerce_core.binding import binding_from_award, offer_hash
from verifund_contracts.terms import validate_requirements

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award_payload() -> dict:
    return {
        "winner": {
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "seller_name": "Northwind Audio",
            "currency": "USD",
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                }
            ],
            "subtotal_cents": 120000,
            "shipping_cents": 3400,
            "total_cents": 123400,
            "delivery_days": 7,
            "warranty_months": 24,
            "returns_days": 30,
        }
    }


class Secrets:
    def __init__(self) -> None:
        self.saved: dict | None = None
        self.projection: dict | None = None

    async def save_secret(self, **kwargs):
        self.saved = kwargs

    async def save_projection(self, run_id, projection):
        self.projection = projection


class Client:
    def __init__(self) -> None:
        self.awards: list[dict] = []
        self.accepts: list[dict] = []
        self.orders: list[dict] = []
        self.funds: list[dict] = []

    async def award(self, request, *, idempotency_key):
        self.awards.append({"request": request, "key": idempotency_key})
        return {
            "transaction_id": "vf_1",
            "agreement_hash": "a" * 64,
            "seller_token": "v1.token",
            "expires_at": "2026-10-30T12:00:00Z",
            "state": "AWARDED",
        }

    async def get_state(self, transaction_id):
        return {
            "transaction_id": transaction_id,
            "state": "AWARDED",
            "last_seq": 1,
            "seller_id": "northwind-audio",
            "amount_cents": 123400,
            "agreement_hash": "a" * 64,
        }

    async def accept(self, transaction_id, **kwargs):
        self.accepts.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "AGREED"}

    async def purchase_order(self, transaction_id, report, *, idempotency_key):
        self.orders.append(
            {
                "transaction_id": transaction_id,
                "report": report,
                "key": idempotency_key,
            }
        )
        return {"state": "FULFILLMENT_PENDING"}

    async def fund(self, transaction_id, request, *, idempotency_key):
        self.funds.append(
            {
                "transaction_id": transaction_id,
                "request": request,
                "key": idempotency_key,
            }
        )
        return {
            "transaction_id": transaction_id,
            "state": "FUNDING_PENDING",
            "checkout_url": "http://control/checkout/fake/token",
            "expires_at": "2026-10-28T12:00:00Z",
        }


def services(mode: str = "fake") -> SimpleNamespace:
    secrets = Secrets()
    client = Client()
    return SimpleNamespace(
        settings=SimpleNamespace(verifund_mode=mode, console_base_url="http://console"),
        settlement=client,
        store=SimpleNamespace(settlement=secrets),
    )


def test_settlement_enabled_only_outside_off_mode():
    assert settlement_enabled(services("fake")) is True
    assert settlement_enabled(services("off")) is False
    assert settlement_enabled(SimpleNamespace(settings=SimpleNamespace(verifund_mode="fake"), settlement=None)) is False


def test_build_award_request_maps_offer_totals():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    assert request.amount_cents == 123400
    assert request.shipping_cents == 3400
    assert request.quantity == 12
    assert request.line_items[0].sku == "NC-700"


async def test_create_award_stores_the_seller_secret_and_projection():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    assert settlement is not None
    assert settlement["transaction_id"] == "vf_1"
    assert settlement["agreement_hash"] == "a" * 64
    assert value.store.settlement.saved["seller_token"] == "v1.token"
    assert value.store.settlement.saved["run_id"] == "run-1"
    assert value.store.settlement.projection["state"] == "AWARDED"
    assert value.settlement.awards[0]["key"] == "award:run-1:offer-1"


async def test_report_acceptance_uses_the_bound_hash_and_total():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    assert settlement is not None
    await report_acceptance(
        value, settlement, seller_task_id="seller-task-1", accepted_at=NOW
    )
    call = value.settlement.accepts[0]
    assert call["seller_id"] == "northwind-audio"
    assert call["agreement_hash"] == "a" * 64
    assert call["accepted_total_cents"] == 123400


async def test_start_funding_uses_console_return_and_cancel_urls():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    assert settlement is not None
    funded = await start_funding(value, "run-1", settlement)
    assert funded["state"] == "FUNDING_PENDING"
    request = value.settlement.funds[0]["request"]
    assert request.return_url == "http://console/runs/run-1"
    assert request.cancel_url == "http://console/runs/run-1"
    assert value.settlement.funds[0]["key"] == "fund:vf_1:v1"


async def test_purchase_order_report_carries_settlement_fields():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    assert settlement is not None
    order = {
        "order_id": "MM-1",
        "offer_id": "offer-1",
        "seller_id": "northwind-audio",
        "quantity": 12,
        "total_cents": 123400,
        "reserved_at": NOW.isoformat(),
        "eta": NOW.isoformat(),
        "tracking_number": "TRK-1",
        "fulfillment": {"carrier": "Northwind Logistics"},
        "line_items": award_payload()["winner"]["line_items"],
    }
    await report_purchase_order(value, "run-1", settlement, order)
    report = value.settlement.orders[0]["report"]
    assert report.seller_order_id == "MM-1"
    assert report.tracking_number == "TRK-1"
    assert report.total_cents == 123400


ATTRIBUTES = {"image_url": "https://images.unsplash.com/photo-x?w=500", "color_name": "gray"}


def test_build_award_request_preserves_attributes_and_binding_version():
    payload = award_payload()
    payload["winner"].update(
        {
            "binding_version": 2,
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "MacBook Air M4 13-inch",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                    "attributes": ATTRIBUTES,
                }
            ],
        }
    )
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, payload)
    assert request.binding_version == 2
    assert request.line_items[0].attributes == ATTRIBUTES
    assert offer_hash(binding_from_award(request.model_dump(mode="json"))) == request.offer_hash


def test_build_award_request_keeps_legacy_offers_on_v1():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    assert request.binding_version == 1
    assert request.line_items[0].attributes == {}
    assert offer_hash(binding_from_award(request.model_dump(mode="json"))) == request.offer_hash


def test_buyer_authors_seven_requirements():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    ids = [r.requirement_id for r in request.requirements]
    assert ids == [
        "product_photos",
        "serial",
        "hardware",
        "warranty",
        "shipping",
        "delivery_confirmation",
        "invoice",
    ]
    validate_requirements(request.requirements)
    by_id = {r.requirement_id: r for r in request.requirements}

    shipping = by_id["shipping"]
    assert shipping.kind == "shipment_manifest"
    assert shipping.source == "reference"
    assert shipping.accepted_formats == []
    shipping_checks = {c.check_id: c.operator for c in shipping.checks}
    assert shipping_checks == {"tracking_matches_po": "eq", "carrier_present": "exists"}

    delivery = by_id["delivery_confirmation"]
    assert delivery.kind == "delivery_confirmation"
    assert delivery.owner == "system"
    assert delivery.source == "reference"
    assert [c.check_id for c in delivery.checks] == ["carrier_and_buyer_agree"]
    assert delivery.checks[0].operator == "exists"

    invoice = by_id["invoice"]
    assert invoice.kind == "invoice"
    assert invoice.source == "file"
    assert invoice.accepted_formats
    invoice_checks = {c.check_id: c for c in invoice.checks}
    assert list(invoice_checks) == [
        "invoice_total_matches",
        "currency_matches",
        "seller_matches",
        "line_items_match",
    ]
    total_check = invoice_checks["invoice_total_matches"]
    assert total_check.operator == "eq"
    assert total_check.expected_value == 123400
    assert total_check.ai_derived is True
    assert invoice_checks["currency_matches"].expected_value == "USD"
    assert invoice_checks["seller_matches"].expected_value == "northwind-audio"
    line_items_check = invoice_checks["line_items_match"]
    assert line_items_check.operator == "contains"
    assert "NC-700" in str(line_items_check.expected_value)

    assert "serial_number" not in by_id
    hardware = by_id["hardware"]
    assert "text/csv" in hardware.accepted_formats
    assert [c.check_id for c in hardware.checks] == ["ram_gte_32gb", "storage_gte_1tb"]


def test_evidence_required_is_deprecated_mirror_of_requirements():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    assert [e.value for e in request.evidence_required] == [
        "shipment_manifest",
        "delivery_confirmation",
        "invoice",
    ]
