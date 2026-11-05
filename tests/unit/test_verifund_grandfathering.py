from __future__ import annotations

from datetime import UTC, datetime

from verifund_contracts.terms import project_requirements

LEGACY_TERMS = {
    "schema": "verifund.agreement.v1",
    "agreement_type": "goods",
    "terms_version": 1,
    "platform_terms_version": "v1",
    "evidence_required": ["shipment_manifest", "delivery_confirmation", "invoice"],
    # no `requirements`, no `policy_version` -> grandfathered (policy_version 1)
}


def test_grandfathered_agreement_projects_evidence_required():
    catalog = project_requirements(LEGACY_TERMS)
    assert [r.requirement_id for r in catalog] == LEGACY_TERMS["evidence_required"]
    by_id = {r.requirement_id: r for r in catalog}
    # Legacy delivery keeps new semantics: system-owned reference requirement.
    assert by_id["delivery_confirmation"].owner == "system"
    assert by_id["delivery_confirmation"].source == "reference"
    assert by_id["shipment_manifest"].owner == "seller"
    assert by_id["shipment_manifest"].source == "file"
    assert all(r.checks for r in catalog)
    assert all(r.required for r in catalog)


def test_terms_with_requirements_are_not_projected():
    terms = {
        "policy_version": 2,
        "evidence_required": ["delivery_confirmation"],
        "requirements": [
            {
                "requirement_id": "hardware",
                "title": "Hardware diagnostic report",
                "description": "Report.",
                "owner": "seller",
                "kind": "other",
                "source": "file",
                "accepted_formats": ["text/csv"],
                "checks": [
                    {
                        "check_id": "ram_gte_32gb",
                        "description": "At least 32 GB RAM.",
                        "expected_value": 32,
                        "operator": "gte",
                        "unit": "GB",
                        "verification_method": "deterministic",
                    }
                ],
                "required": True,
            }
        ],
    }
    catalog = project_requirements(terms)
    assert [r.requirement_id for r in catalog] == ["hardware"]
    assert catalog[0].checks[0].check_id == "ram_gte_32gb"


def test_new_agreements_store_policy_version():
    from verifund_control_plane.agreements.generator import build_terms

    from tests.unit.test_agreement_generator import _award

    terms = build_terms(_award(), datetime.now(UTC))
    assert terms["policy_version"] == 2
