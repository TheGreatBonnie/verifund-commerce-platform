from __future__ import annotations

from verifund_contracts.models import (
    ActionOwner,
    CarrierEventStatus,
    DisputeClaimType,
    Requirement,
)
from verifund_contracts.terms import project_requirements


def test_project_requirements_defaults_for_legacy_terms() -> None:
    reqs = project_requirements({"evidence_required": ["serial", "invoice"]})
    serial = next(r for r in reqs if r.requirement_id == "serial")
    assert serial.stage is None
    assert serial.min_items == 1
    assert serial.required_views == []


def test_project_requirements_laptop_category_emits_staged_catalog() -> None:
    terms = {
        "product": {"category": "electronics.laptop.refurbished"},
        "evidence_required": ["serial", "invoice"],
    }
    reqs = project_requirements(terms)
    ids = {r.requirement_id for r in reqs}
    for required_id in {
        "serial",
        "provenance",
        "product_photos",
        "condition_declaration",
        "hardware",
        "battery",
        "warranty",
        "packaging",
        "shipping",
        "insurance_confirmation",
        "carrier_acceptance",
        "delivery_confirmation",
        "invoice",
    }:
        assert required_id in ids

    photos = next(r for r in reqs if r.requirement_id == "product_photos")
    assert photos.stage == "product_condition"
    assert photos.min_items == 7
    assert "serial" in photos.required_views

    decl = next(r for r in reqs if r.requirement_id == "condition_declaration")
    assert decl.source == "declaration"
    assert decl.owner == "seller"

    owners = {r.requirement_id: r.owner for r in reqs}
    assert owners["carrier_acceptance"] == "system"
    assert owners["delivery_confirmation"] == "system"


def test_new_enums_exist() -> None:
    assert ActionOwner.SELLER.value == "seller"
    assert CarrierEventStatus.PICKED_UP.value == "PICKED_UP"
    assert DisputeClaimType.WRONG_DEVICE.value == "WRONG_DEVICE"
