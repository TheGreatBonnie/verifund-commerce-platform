from __future__ import annotations

import copy
from typing import Any

from verifund_contracts.models import AwardRequest, Requirement, RequirementCheck


def policy_version_of(terms: dict[str, Any]) -> int:
    """The stored policy version for agreement terms; missing means legacy."""
    try:
        return int(terms.get("policy_version") or 1)
    except (TypeError, ValueError):
        return 1


_LEGACY_FILE_FORMATS = [
    "application/json",
    "application/pdf",
    "text/csv",
    "image/jpeg",
    "image/png",
    "image/webp",
]

_IMAGE_FORMATS = ["image/jpeg", "image/png", "image/webp"]
_DIAGNOSTIC_FORMATS = list(_LEGACY_FILE_FORMATS)
_LAPTOP_CATEGORY = "electronics.laptop.refurbished"


def _category_of(terms: dict[str, Any]) -> str | None:
    product = terms.get("product") or {}
    category = product.get("category") or terms.get("category")
    return str(category) if category else None


def _legacy_requirement(requirement_id: str) -> Requirement:
    if requirement_id == "delivery_confirmation":
        return Requirement(
            requirement_id="delivery_confirmation",
            title="Delivery confirmation",
            description=(
                "Legacy requirement projected from `evidence_required`; delivery "
                "is system-sourced (carrier record plus buyer confirmation)."
            ),
            owner="system",
            kind="delivery_confirmation",
            source="reference",
            checks=[
                RequirementCheck(
                    check_id="carrier_and_buyer_agree",
                    description="Carrier record and buyer confirmation agree on delivery.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        )
    return Requirement(
        requirement_id=requirement_id,
        title=requirement_id.replace("_", " ").title(),
        description=(
            f"Legacy requirement projected from `evidence_required` "
            f"({requirement_id})."
        ),
        owner="seller",
        kind=requirement_id,
        source="file",
        accepted_formats=list(_LEGACY_FILE_FORMATS),
        checks=[
            RequirementCheck(
                check_id=f"{requirement_id}_present",
                description=f"{requirement_id} evidence is present and legible.",
                operator="exists",
                verification_method="deterministic",
            ),
        ],
        required=True,
    )


def _laptop_requirement_catalog() -> list[Requirement]:
    return [
        Requirement(
            requirement_id="serial",
            title="Serial number",
            description="Device serial label and readable serial value.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_identity",
            accepted_formats=list(_IMAGE_FORMATS),
            checks=[
                RequirementCheck(
                    check_id="serial_readable",
                    description="Serial number is readable.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="provenance",
            title="Provenance challenge",
            description="Transaction challenge code visible on the device.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_identity",
            accepted_formats=list(_IMAGE_FORMATS),
            checks=[
                RequirementCheck(
                    check_id="challenge_code",
                    description="Challenge code matches the active transaction challenge.",
                    operator="eq",
                    expected_value=None,
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="product_photos",
            title="Condition photos",
            description="Multi-angle baseline photos of the laptop.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_condition",
            accepted_formats=list(_IMAGE_FORMATS),
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
            required=True,
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
            required=True,
        ),
        Requirement(
            requirement_id="hardware",
            title="Hardware diagnostics",
            description="Diagnostic report matching agreed specifications.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=list(_DIAGNOSTIC_FORMATS),
            checks=[
                RequirementCheck(
                    check_id="ram_gte_32gb",
                    description="RAM meets the agreed minimum.",
                    operator="gte",
                    expected_value=32,
                    unit="GB",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="storage_gte_1tb",
                    description="Storage meets the agreed minimum.",
                    operator="gte",
                    expected_value=1024,
                    unit="GB",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="battery",
            title="Battery report",
            description="Battery health and cycle evidence.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=list(_DIAGNOSTIC_FORMATS),
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
            required=True,
        ),
        Requirement(
            requirement_id="warranty",
            title="Warranty",
            description="Warranty or coverage evidence.",
            owner="seller",
            kind="other",
            source="file",
            stage="product_compliance",
            accepted_formats=list(_DIAGNOSTIC_FORMATS),
            checks=[
                RequirementCheck(
                    check_id="warranty_gte_90_days",
                    description="Warranty meets the agreed minimum.",
                    operator="gte",
                    expected_value=90,
                    unit="days",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="packaging",
            title="Packaging photos",
            description="Unit with serial, inside box, and sealed box with label.",
            owner="seller",
            kind="shipment_manifest",
            source="file",
            stage="packaging",
            accepted_formats=list(_IMAGE_FORMATS),
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
            required=True,
        ),
        Requirement(
            requirement_id="shipping",
            title="Shipping details",
            description="Carrier and tracking reference.",
            owner="seller",
            kind="shipment_manifest",
            source="reference",
            stage="packaging",
            checks=[
                RequirementCheck(
                    check_id="carrier_present",
                    description="Carrier is present.",
                    operator="exists",
                    verification_method="deterministic",
                ),
                RequirementCheck(
                    check_id="tracking_present",
                    description="Tracking number is present.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="insurance_confirmation",
            title="Shipping insurance",
            description="Coverage confirmation when required by policy or value.",
            owner="seller",
            kind="other",
            source="file",
            stage="packaging",
            accepted_formats=list(_DIAGNOSTIC_FORMATS),
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
            required=True,
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
                    check_id="delivered",
                    description="Carrier delivery event exists.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="invoice",
            title="Invoice",
            description="Seller invoice for the transaction.",
            owner="seller",
            kind="invoice",
            source="file",
            stage="packaging",
            accepted_formats=list(_DIAGNOSTIC_FORMATS),
            checks=[
                RequirementCheck(
                    check_id="invoice_present",
                    description="Invoice is present.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
    ]


def project_requirements(terms: dict[str, Any]) -> list[Requirement]:
    """Project the requirement catalog from stored agreement terms.

    Agreements authored with the catalog carry ``requirements[]`` (copied from
    ``AwardRequest.requirements`` by the generator). Grandfathered
    (``policy_version`` 1) agreements are projected at read time from their
    legacy ``evidence_required`` list. Laptop agreements without an explicit
    catalog project the laptop template while preserving any additional legacy
    evidence ids named by the agreement.
    """
    raw = terms.get("requirements") or []
    if raw:
        reqs = [Requirement.model_validate(item) for item in raw]
        return [
            r.model_copy(
                update={
                    "min_items": getattr(r, "min_items", 1) or 1,
                    "required_views": list(getattr(r, "required_views", None) or []),
                }
            )
            for r in reqs
        ]
    if _category_of(terms) == _LAPTOP_CATEGORY:
        base = {r.requirement_id: r for r in _laptop_requirement_catalog()}
        for kind in terms.get("evidence_required") or []:
            kind_id = str(kind)
            base.setdefault(kind_id, _legacy_requirement(kind_id))
        return list(base.values())
    return [_legacy_requirement(str(kind)) for kind in terms.get("evidence_required") or []]


def validate_requirements(requirements: list[Requirement]) -> None:
    """Enforce the creation floors from spec §3.1.1 (decisions 24/25).

    Floors: non-empty list; unique ``requirement_id``; unique ``check_id`` within a
    requirement; non-empty ``checks``; ``accepted_formats`` non-empty when
    ``source == "file"``; ``owner`` present on every entry; ``expected_value`` present
    whenever ``operator != "exists"`` and the check is not AI-derived; exactly one
    system-owned ``delivery_confirmation`` requirement.

    The delivery requirement is identified by ``requirement_id == "delivery_confirmation"``
    because ``requirement_id`` is the stable addressing key (decision 36) and the
    acceptance clock keys off it; the canonical catalog also sets
    ``kind == "delivery_confirmation"`` (§3.9.2), which is not floor-checked here.
    """
    if not requirements:
        raise ValueError("invalid_requirements")
    seen_ids: set[str] = set()
    for requirement in requirements:
        if requirement.requirement_id in seen_ids:
            raise ValueError("invalid_requirements")
        seen_ids.add(requirement.requirement_id)
        if not requirement.owner or not requirement.owner.strip():
            raise ValueError("invalid_requirements")
        if requirement.source == "file" and not requirement.accepted_formats:
            raise ValueError("invalid_requirements")
        if not requirement.checks:
            raise ValueError("invalid_requirements")
        seen_checks: set[str] = set()
        for check in requirement.checks:
            if check.check_id in seen_checks:
                raise ValueError("invalid_requirements")
            seen_checks.add(check.check_id)
            if (
                check.operator != "exists"
                and not check.ai_derived
                and check.expected_value is None
            ):
                raise ValueError("invalid_requirements")
    delivery = [r for r in requirements if r.requirement_id == "delivery_confirmation"]
    if len(delivery) != 1 or delivery[0].owner != "system":
        raise ValueError("invalid_requirements")


def validate_terms(terms: dict[str, Any], award: AwardRequest | None = None) -> None:
    if terms.get("schema") != "verifund.agreement.v1":
        raise ValueError("invalid_terms")
    if terms.get("agreement_type") != "goods":
        raise ValueError("invalid_terms")
    if terms.get("terms_version") != 1:
        raise ValueError("invalid_terms")
    parties = terms.get("parties", {})
    offer = terms.get("offer", {})
    if award is not None:
        if parties.get("buyer", {}).get("id") != award.buyer_id:
            raise ValueError("invalid_terms")
        if parties.get("seller", {}).get("id") != award.seller_id:
            raise ValueError("invalid_terms")
        if offer.get("offer_id") != award.offer_id:
            raise ValueError("invalid_terms")
        if offer.get("offer_round") != award.offer_round:
            raise ValueError("offer_mismatch")
        if offer.get("offer_hash") != award.offer_hash:
            raise ValueError("offer_mismatch")
    totals = terms.get("totals", {})
    if totals.get("currency") != "USD":
        raise ValueError("invalid_terms")
    items = terms.get("items", [])
    if not items:
        raise ValueError("invalid_terms")
    skus = [i.get("sku") for i in items]
    if len(set(skus)) != len(skus):
        raise ValueError("invalid_terms")
    subtotal = sum(
        (i.get("unit_price_cents", 0) + i.get("warranty_addon_cents", 0)) * i.get("quantity", 0)
        for i in items
    )
    if subtotal != totals.get("subtotal_cents"):
        raise ValueError("invalid_terms")
    if totals.get("total_cents") != (
        totals.get("subtotal_cents", 0) + totals.get("shipping_cents", 0)
        + totals.get("tax_cents", 0) + totals.get("fees_cents", 0)
    ):
        raise ValueError("invalid_terms")
    if any(i.get("quantity", 0) <= 0 for i in items):
        raise ValueError("invalid_terms")
    if any(i.get("unit_price_cents", 0) < 0 for i in items):
        raise ValueError("invalid_terms")
    delivery = terms.get("delivery", {})
    if delivery.get("delivery_days", 0) < 1:
        raise ValueError("invalid_terms")
    inspection = terms.get("inspection", {})
    if inspection.get("period_hours", 0) < 1:
        raise ValueError("invalid_terms")
    evidence = terms.get("evidence_required", [])
    if not evidence or "delivery_confirmation" not in evidence:
        raise ValueError("invalid_terms")
    if terms.get("dispute_window_hours", 0) < 1:
        raise ValueError("invalid_terms")
    remedies = terms.get("remedies", {})
    if not all(k in remedies for k in ("non_delivery", "late_delivery", "damaged_goods")):
        raise ValueError("invalid_terms")
    if terms.get("totals", {}).get("total_cents", 0) != totals.get("subtotal_cents", 0) + totals.get("shipping_cents", 0) + totals.get("tax_cents", 0) + totals.get("fees_cents", 0):
        raise ValueError("invalid_terms")
    if award is not None and terms.get("totals", {}).get("total_cents", 0) != award.amount_cents:
        raise ValueError("invalid_terms")


def apply_change_set(base_terms: dict[str, Any], change_set: Any) -> dict[str, Any]:
    terms = copy.deepcopy(base_terms)
    items_by_sku = {i["sku"]: i for i in terms["items"]}
    if isinstance(change_set, (list, tuple)):
        operations = change_set
    elif hasattr(change_set, "operations"):
        operations = change_set.operations
    else:
        operations = [change_set]
    for op in operations:
        kind = op.op.value if hasattr(op.op, "value") else str(op.op)

        def _required(name: str, _op=op):
            value = getattr(_op, name)
            if value is None:
                raise ValueError("invalid_change_set")
            return value

        if kind == "set_unit_price":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["unit_price_cents"] = _required("unit_price_cents")
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * items_by_sku[op.sku]["quantity"]
        elif kind == "set_quantity":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            quantity = _required("quantity")
            if quantity <= 0:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["quantity"] = quantity
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * quantity
        elif kind == "set_shipping":
            terms["totals"]["shipping_cents"] = _required("shipping_cents")
        elif kind == "set_tax":
            terms["totals"]["tax_cents"] = _required("tax_cents")
        elif kind == "set_fees":
            terms["totals"]["fees_cents"] = _required("fees_cents")
        elif kind == "set_delivery_days":
            terms["delivery"]["delivery_days"] = _required("delivery_days")
        elif kind == "set_warranty_months":
            terms["warranty_months"] = _required("warranty_months")
        elif kind == "set_returns_days":
            terms["returns_days"] = _required("returns_days")
        elif kind == "set_inspection_period":
            terms["inspection"]["period_hours"] = _required("inspection_period_hours")
        elif kind == "set_evidence_required":
            evidence = _required("evidence_required")
            evidence_values = [e.value if hasattr(e, "value") else str(e) for e in evidence]
            if "delivery_confirmation" not in evidence_values:
                raise ValueError("invalid_change_set")
            terms["evidence_required"] = evidence_values
        elif kind == "set_remedies":
            remedies = _required("remedies")
            terms["remedies"] = remedies.model_dump(mode="json")
            if getattr(op, "dispute_window_hours", None) is not None:
                terms["dispute_window_hours"] = op.dispute_window_hours
        else:
            raise ValueError("invalid_change_set")
        # recompute subtotal/total
        terms["totals"]["subtotal_cents"] = sum(i["line_total_cents"] for i in terms["items"])
        terms["totals"]["total_cents"] = (
            terms["totals"]["subtotal_cents"] + terms["totals"]["shipping_cents"]
            + terms["totals"]["tax_cents"] + terms["totals"]["fees_cents"]
        )
    return terms
