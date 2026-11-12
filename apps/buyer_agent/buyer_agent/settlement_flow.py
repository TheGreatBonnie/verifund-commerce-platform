from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from commerce_core.binding import canonical_offer_binding, offer_hash
from commerce_core.contracts import Offer
from verifund_contracts import (
    AwardLineItem,
    AwardRequest,
    CancelReason,
    CancelRequest,
    EvidenceKind,
    FundRequest,
    PurchaseOrderLineItem,
    PurchaseOrderReport,
    RejectReason,
    ReleaseRequest,
    Requirement,
    RequirementCheck,
)


def settlement_enabled(services: Any) -> bool:
    settings = getattr(services, "settings", None)
    if getattr(settings, "verifund_mode", "off") == "off":
        return False
    return getattr(services, "settlement", None) is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Requirement ids with no counterpart in the deprecated `EvidenceKind` vocabulary are
# omitted from the mirror (`product_photos`, `serial`, `hardware`, `warranty`); the mirror
# exists only so grandfathered callers keep working, so it stays byte-identical to the
# legacy `evidence_required` authoring.
_LEGACY_EVIDENCE_KIND_BY_REQUIREMENT_ID = {
    "shipping": EvidenceKind.SHIPMENT_MANIFEST,
    "delivery_confirmation": EvidenceKind.DELIVERY_CONFIRMATION,
    "invoice": EvidenceKind.INVOICE,
}


def _legacy_evidence_required(requirements: list[Requirement]) -> list[EvidenceKind]:
    return [
        _LEGACY_EVIDENCE_KIND_BY_REQUIREMENT_ID[requirement.requirement_id]
        for requirement in requirements
        if requirement.requirement_id in _LEGACY_EVIDENCE_KIND_BY_REQUIREMENT_ID
    ]


def _requirement_catalog(
    *,
    winner: dict[str, Any],
    seller_id: str,
    amount_cents: int,
    currency: str,
) -> list[Requirement]:
    """Buyer-authored laptop requirement catalog aligned to the 2026-11-12 spec."""
    line_items = winner["line_items"]
    line_items_expected = ", ".join(
        f"{item['sku']} x{item['quantity']}" for item in line_items
    )
    image_formats = ["image/jpeg", "image/png", "image/webp"]
    diag_formats = ["application/json", "application/pdf", "text/csv", "image/jpeg", "image/png", "image/webp"]
    return [
        Requirement(
            requirement_id="serial",
            title="Serial number",
            description="Clear photograph of the device serial number label.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_identity",
            accepted_formats=image_formats,
            checks=[
                RequirementCheck(
                    check_id="serial_readable",
                    description="Serial number is readable.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="provenance",
            title="Provenance challenge",
            description="Photograph showing the active Verifund challenge code on the device.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_identity",
            accepted_formats=image_formats,
            checks=[
                RequirementCheck(
                    check_id="challenge_code",
                    description="Challenge code matches the active transaction challenge.",
                    operator="eq",
                    expected_value="runtime:active_provenance_challenge",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="product_photos",
            title="Condition photos",
            description="Multi-angle baseline photos of the laptop.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_condition",
            accepted_formats=image_formats + ["video/mp4"],
            min_items=7,
            required_views=["front", "back", "left", "right", "keyboard", "screen", "underside", "serial"],
            checks=[
                RequirementCheck(
                    check_id="views_cover",
                    description="Required condition views are covered.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="condition_declaration",
            title="Condition declaration",
            description="Structured condition, lock, and accessory declaration.",
            owner="seller",
            kind="other",
            source="declaration",
            stage="product_condition",
            checks=[
                RequirementCheck(
                    check_id="locks_disabled",
                    description="Device locks and management enrollment are cleared.",
                    operator="eq",
                    expected_value="true",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="battery_health_declared",
                    description="Battery health is declared.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="hardware",
            title="Hardware diagnostic report",
            description="Diagnostic report showing at least 32 GB of RAM and 1 TB of storage.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=diag_formats + ["video/mp4"],
            checks=[
                RequirementCheck(
                    check_id="ram_gte_32gb",
                    description="At least 32 GB of RAM.",
                    expected_value=32,
                    operator="gte",
                    unit="GB",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="storage_gte_1tb",
                    description="At least 1 TB of storage.",
                    expected_value=1024,
                    operator="gte",
                    unit="GB",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="battery",
            title="Battery report",
            description="Battery health and cycle evidence.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=diag_formats,
            checks=[
                RequirementCheck(
                    check_id="battery_health_pct",
                    description="Battery health meets the agreed threshold.",
                    operator="gte",
                    expected_value=80,
                    unit="%",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="warranty",
            title="Warranty documentation",
            description="Warranty documentation covering at least 90 days from delivery.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=diag_formats,
            checks=[
                RequirementCheck(
                    check_id="warranty_gte_90_days",
                    description="Warranty covers at least 90 days.",
                    expected_value=90,
                    operator="gte",
                    unit="days",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="packaging",
            title="Packaging photos",
            description="Photos showing unit with serial, inside box, and sealed box with label.",
            owner="seller",
            kind="shipment_manifest",
            source="file",
            stage="packaging",
            accepted_formats=image_formats,
            min_items=3,
            required_views=["unit_with_serial", "inside_box", "sealed_with_label"],
            checks=[
                RequirementCheck(
                    check_id="views_cover",
                    description="Required packaging views are covered.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="shipping",
            title="Shipping information",
            description="Carrier and tracking number matching the purchase order.",
            owner="seller",
            kind="shipment_manifest",
            source="reference",
            stage="packaging",
            checks=[
                RequirementCheck(
                    check_id="tracking_matches_po",
                    description="Tracking number matches the tracking number on the purchase order.",
                    expected_value="purchase_order.tracking_number",
                    operator="eq",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="carrier_present",
                    description="Carrier is present on the shipping reference.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="insurance_confirmation",
            title="Shipping insurance",
            description="Coverage confirmation when required by policy or value.",
            owner="seller",
            kind="other",
            source="file",
            stage="packaging",
            accepted_formats=diag_formats,
            required=False,
            checks=[
                RequirementCheck(
                    check_id="insured_value_sufficient",
                    description="Insured value covers the declared value when required.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="carrier_acceptance",
            title="Carrier acceptance",
            description="Carrier accepted the package (system-sourced).",
            owner="system",
            kind="shipment_manifest",
            source="reference",
            stage="delivery",
            checks=[
                RequirementCheck(
                    check_id="carrier_accepted",
                    description="Carrier acceptance event exists.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="delivery_confirmation",
            title="Delivery confirmation",
            description="Carrier delivery confirmation and proof of delivery as required.",
            owner="system",
            kind="delivery_confirmation",
            source="reference",
            stage="delivery",
            checks=[
                RequirementCheck(
                    check_id="carrier_and_buyer_agree",
                    description="Carrier delivery evidence satisfies the requirement.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
        ),
        Requirement(
            requirement_id="invoice",
            title="Invoice",
            description=(
                "Invoice matching the agreement totals, currency, seller, and line items. "
                "Machine-readable uploads (application/json, text/csv) must carry "
                "`total_cents`, `currency`, `seller_id`, and `line_items` as "
                '`"SKU xQTY"` strings.'
            ),
            owner="seller",
            kind="invoice",
            source="file",
            stage="packaging",
            accepted_formats=diag_formats,
            checks=[
                RequirementCheck(
                    check_id="invoice_total_matches",
                    description="Invoice total matches the agreement total.",
                    expected_value=amount_cents,
                    operator="eq",
                    unit="cents",
                    verification_method="deterministic",
                    ai_derived=False,
                ),
                RequirementCheck(
                    check_id="currency_matches",
                    description="Invoice currency matches the agreement currency.",
                    expected_value=currency,
                    operator="eq",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="seller_matches",
                    description="Invoice seller matches the agreement seller.",
                    expected_value=seller_id,
                    operator="eq",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="line_items_match",
                    description="Invoice contains the award line items.",
                    expected_value=line_items_expected,
                    operator="contains",
                    verification_method="deterministic",
                    ai_derived=False,
                ),
            ],
        ),
    ]


def build_award_request(
    run_id: str, mandate: dict[str, Any], award: dict[str, Any]
) -> AwardRequest:
    winner = award["winner"]
    normalized = {
        "offer_id": winner["offer_id"],
        "request_id": winner.get("request_id") or f"rfq-{run_id}",
        "seller_id": winner["seller_id"],
        "seller_name": winner.get("seller_name") or winner["seller_id"],
        "seller_rating": winner.get("seller_rating", 4.5),
        "currency": winner.get("currency", "USD"),
        "line_items": [
            {
                "sku": item["sku"],
                "name": item["name"],
                "quantity": item["quantity"],
                "unit_price_cents": item["unit_price_cents"],
                "list_unit_price_cents": item.get(
                    "list_unit_price_cents", item["unit_price_cents"]
                ),
                "warranty_addon_cents": item.get("warranty_addon_cents", 0),
                "attributes": item.get("attributes") or {},
            }
            for item in winner["line_items"]
        ],
        "subtotal_cents": winner.get(
            "subtotal_cents",
            sum(
                (i["unit_price_cents"] + i.get("warranty_addon_cents", 0))
                * i["quantity"]
                for i in winner["line_items"]
            ),
        ),
        "shipping_cents": winner.get("shipping_cents", 0),
        "tax_cents": winner.get("tax_cents", 0),
        "fees_cents": winner.get("fees_cents", 0),
        "total_cents": winner["total_cents"],
        "delivery_days": winner["delivery_days"],
        "warranty_months": winner["warranty_months"],
        "returns_days": winner["returns_days"],
        "round": winner.get("round", 1),
        "binding_version": winner.get("binding_version", 1),
        "valid_until": winner.get("valid_until")
        or (datetime.now(UTC) + timedelta(hours=1)),
    }
    offer = Offer.model_validate(normalized)
    computed_offer_hash = offer_hash(canonical_offer_binding(offer))
    requirements = _requirement_catalog(
        winner=winner,
        seller_id=winner["seller_id"],
        amount_cents=winner["total_cents"],
        currency=winner.get("currency", "USD"),
    )
    return AwardRequest(
        run_id=run_id,
        buyer_id=str(mandate.get("buyer_id") or "demo-buyer"),
        seller_id=winner["seller_id"],
        offer_id=winner["offer_id"],
        request_id=winner.get("request_id") or f"rfq-{run_id}",
        buyer_display_name=str(mandate.get("buyer_id") or "Demo Buyer"),
        seller_display_name=winner.get("seller_name") or winner["seller_id"],
        currency=winner.get("currency", "USD"),
        amount_cents=winner["total_cents"],
        shipping_cents=winner.get("shipping_cents", 0),
        tax_cents=winner.get("tax_cents", 0),
        fees_cents=winner.get("fees_cents", 0),
        quantity=sum(item["quantity"] for item in winner["line_items"]),
        line_items=[
            AwardLineItem(
                sku=item["sku"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                warranty_addon_cents=item.get("warranty_addon_cents", 0),
                attributes=item.get("attributes") or {},
            )
            for item in winner["line_items"]
        ],
        binding_version=winner.get("binding_version", 1),
        delivery_days=winner["delivery_days"],
        warranty_months=winner["warranty_months"],
        returns_days=winner["returns_days"],
        offer_round=winner.get("round", 1),
        offer_hash=winner.get("offer_hash") or computed_offer_hash,
        offer_valid_until=winner.get("valid_until")
        or datetime.now(UTC) + timedelta(hours=1),
        inspection_period_hours=48,
        inspection_starts_on="DELIVERY_CONFIRMED",
        requirements=requirements,
        # DEPRECATED mirror of the requirement ids, derived for grandfathered callers.
        evidence_required=_legacy_evidence_required(requirements),
        dispute_window_hours=72,
    )


async def create_award(
    services: Any,
    run_id: str,
    mandate: dict[str, Any],
    award: dict[str, Any],
) -> dict[str, Any] | None:
    if not settlement_enabled(services):
        return None
    request = build_award_request(run_id, mandate, award)
    response = await services.settlement.award(
        request, idempotency_key=f"award:{run_id}:{request.offer_id}"
    )
    expires_at = response["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    await services.store.settlement.save_secret(
        run_id=run_id,
        transaction_id=response["transaction_id"],
        seller_id=request.seller_id,
        purpose="settlement",
        seller_token=response["seller_token"],
        expires_at=expires_at,
    )
    projection = await services.settlement.get_state(response["transaction_id"])
    await services.store.settlement.save_projection(run_id, projection)
    return {
        "transaction_id": response["transaction_id"],
        "agreement_hash": response["agreement_hash"],
        "offer_hash": request.offer_hash,
        "agreement_version": response.get("agreement_version", 1),
        "seller_id": request.seller_id,
        "offer_id": request.offer_id,
        "amount_cents": request.amount_cents,
        "seller_token_expires_at": response["expires_at"],
        "state": "AWARDED",
        "projection": projection,
    }


async def ensure_seller_token(
    services: Any,
    run_id: str,
    settlement: dict[str, Any],
    *,
    threshold_hours: int = 24,
) -> dict[str, Any]:
    secret = await services.store.settlement.get_secret(
        run_id, settlement["transaction_id"], "settlement"
    )
    if secret is None:
        return settlement
    expires_at = secret["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at - datetime.now(UTC) > timedelta(hours=threshold_hours):
        return settlement
    response = await services.settlement.reissue_seller_token(
        transaction_id=settlement["transaction_id"],
        run_id=run_id,
        seller_id=settlement["seller_id"],
        purpose="settlement",
    )
    refreshed = response["expires_at"]
    if isinstance(refreshed, str):
        refreshed = datetime.fromisoformat(refreshed)
    await services.store.settlement.save_secret(
        run_id=run_id,
        transaction_id=settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        purpose="settlement",
        seller_token=response["seller_token"],
        expires_at=refreshed,
    )
    return {
        **settlement,
        "seller_token_expires_at": response["expires_at"],
    }


async def report_acceptance(
    services: Any,
    settlement: dict[str, Any],
    *,
    seller_task_id: str,
    accepted_at: datetime,
) -> dict[str, Any]:
    return await services.settlement.accept(
        settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        agreement_hash=settlement["agreement_hash"],
        accepted_total_cents=settlement["amount_cents"],
        seller_task_id=seller_task_id,
        accepted_at=_iso(accepted_at),
        agreement_version=settlement.get("agreement_version"),
        offer_hash=settlement.get("offer_hash"),
    )


def _reject_reason(error: dict[str, Any] | None) -> RejectReason:
    details = (error or {}).get("details") or {}
    raw = details.get("reason_code") or (error or {}).get("reason_code")
    try:
        return RejectReason(str(raw)) if raw else RejectReason.TERMS_MISMATCH
    except ValueError:
        return RejectReason.OTHER


async def report_rejection(
    services: Any,
    settlement: dict[str, Any],
    *,
    seller_task_id: str,
    rejected_at: datetime,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    return await services.settlement.reject(
        settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        agreement_hash=settlement["agreement_hash"],
        reason_code=_reject_reason(error).value,
        note=str((error or {}).get("message") or "Seller declined the agreement"),
        seller_task_id=seller_task_id,
        rejected_at=_iso(rejected_at),
    )


async def report_approval(
    services: Any,
    settlement: dict[str, Any],
    approval: dict[str, Any],
) -> dict[str, Any]:
    if not approval.get("approved"):
        return await services.settlement.cancel(
            settlement["transaction_id"],
            CancelRequest(
                reason_code=CancelReason.BUYER_REJECTED,
                note=str(approval.get("note") or ""),
            ),
        )
    return await services.settlement.approve(
        settlement["transaction_id"],
        approval_id=str(uuid.uuid4()),
        approved_by=str(approval["approved_by"]),
        approved_at=_iso(datetime.now(UTC)),
        note=str(approval.get("note") or ""),
        agreement_hash=settlement["agreement_hash"],
        agreement_version=settlement.get("agreement_version"),
    )


async def start_funding(
    services: Any, run_id: str, settlement: dict[str, Any]
) -> dict[str, Any]:
    console = str(services.settings.console_base_url).rstrip("/")
    request = FundRequest(
        agreement_hash=settlement["agreement_hash"],
        agreement_version=settlement.get("agreement_version", 1),
        return_url=f"{console}/runs/{run_id}",
        cancel_url=f"{console}/runs/{run_id}",
    )
    return await services.settlement.fund(
        settlement["transaction_id"],
        request,
        idempotency_key=f"fund:{settlement['transaction_id']}:v1",
    )


async def refresh_funding(
    services: Any, settlement: dict[str, Any]
) -> dict[str, Any]:
    return await services.settlement.refresh_funding(
        settlement["transaction_id"]
    )


async def report_purchase_order(
    services: Any,
    run_id: str,
    settlement: dict[str, Any],
    order: dict[str, Any],
) -> dict[str, Any]:
    report = PurchaseOrderReport(
        agreement_hash=settlement["agreement_hash"],
        seller_order_id=str(order["order_id"]),
        offer_id=str(order["offer_id"]),
        quantity=int(order["quantity"]),
        total_cents=int(order["total_cents"]),
        currency=str(order.get("currency", "USD")),
        tracking_number=str(order["tracking_number"]),
        carrier=str((order.get("fulfillment") or {}).get("carrier") or "Unknown"),
        reserved_at=order["reserved_at"],
        eta=order["eta"],
        line_items=[
            PurchaseOrderLineItem(
                sku=item["sku"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                warranty_addon_cents=item.get("warranty_addon_cents", 0),
            )
            for item in order["line_items"]
        ],
    )
    return await services.settlement.purchase_order(
        settlement["transaction_id"],
        report,
        idempotency_key=f"po:{settlement['transaction_id']}",
    )


async def fetch_state(services: Any, settlement: dict[str, Any]) -> dict[str, Any]:
    projection = await services.settlement.get_state(
        settlement["transaction_id"]
    )
    settlement["projection"] = projection
    settlement["state"] = projection["state"]
    return projection


async def release_transaction(
    services: Any,
    settlement: dict[str, Any],
    *,
    released_by: str,
    note: str,
    override: bool,
) -> dict[str, Any]:
    return await services.settlement.release(
        settlement["transaction_id"],
        ReleaseRequest(
            released_by=released_by, note=note, override=override
        ),
    )


def settle_with_secret_ref(
    settlement: dict[str, Any], run_id: str, purpose: str
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "transaction_id": settlement["transaction_id"],
        "seller_id": settlement["seller_id"],
        "purpose": purpose,
    }
