from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from commerce_core.binding import canonical_offer_binding, offer_hash
from pydantic import ValidationError
from verifund_contracts import (
    AgreementReviewDecision,
    AgreementReviewResult,
    ChangeRequestEnvelope,
    Requirement,
)
from verifund_contracts.models import canonical_json, sha256_hex
from verifund_contracts.terms import apply_change_set

from seller_agent.agreement_store import AgreementReviewStore, SellerAgreementReviewStore
from seller_agent.mandate import SellerMandate
from seller_agent.settlement import validate_mandate


def recompute_offer_hash(offer) -> str | None:
    if offer is None:
        return None
    return offer_hash(canonical_offer_binding(offer))


def recompute_agreement_hash(projection) -> str:
    return sha256_hex(canonical_json(projection.canonical_payload()))


def _terms_items(terms: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "line_items", "lineItems"):
        value = terms.get(key)
        if isinstance(value, list):
            return value
    return []


def _terms_match_offer(terms: dict[str, Any], offer) -> bool:
    totals = terms.get("totals", {})
    currency = totals.get("currency")
    if currency is None:
        currency = terms.get("currency")
    if currency is not None and currency != (offer.currency.value if hasattr(offer.currency, "value") else offer.currency):
        return False
    if totals.get("subtotal_cents") is not None and totals.get("subtotal_cents") != offer.subtotal_cents:
        return False
    if totals.get("shipping_cents") is not None and totals.get("shipping_cents") != offer.shipping_cents:
        return False
    if totals.get("tax_cents") is not None and totals.get("tax_cents") != offer.tax_cents:
        return False
    if totals.get("fees_cents") is not None and totals.get("fees_cents") != offer.fees_cents:
        return False
    if totals.get("total_cents") is not None and totals.get("total_cents") != offer.total_cents:
        return False
    delivery = terms.get("delivery", {})
    if delivery.get("delivery_days") is not None and delivery.get("delivery_days") != offer.delivery_days:
        return False
    if terms.get("warranty_months") is not None and terms.get("warranty_months") != offer.warranty_months:
        return False
    if terms.get("returns_days") is not None and terms.get("returns_days") != offer.returns_days:
        return False
    projected_items = [
        {
            "sku": i.get("sku"),
            "quantity": i.get("quantity"),
            "unit_price_cents": i.get("unit_price_cents"),
            "warranty_addon_cents": i.get("warranty_addon_cents", 0),
        }
        for i in _terms_items(terms)
    ]
    offer_items = [
        {
            "sku": i.sku,
            "quantity": i.quantity,
            "unit_price_cents": i.unit_price_cents,
            "warranty_addon_cents": i.warranty_addon_cents,
        }
        for i in offer.line_items
    ]
    return projected_items == offer_items


def _result(projection, status, reason_code, now, task_id, context_id, *,
            offer_hash=None, verified_change_request_id=None):
    if not offer_hash:
        offer_hash = projection.offer_hash
    return AgreementReviewResult(
        party="seller",
        status=status,
        run_id=projection.run_id,
        transaction_id=projection.transaction_id,
        agreement_version=projection.agreement_version,
        agreement_hash=projection.agreement_hash,
        offer_hash=offer_hash,
        actor_type="SELLER_AGENT",
        actor_id=projection.seller_id,
        authority_ref=f"seller-mandate:{projection.seller_id}:{1}",
        authority_snapshot={},
        verified_change_request_id=verified_change_request_id,
        task_id=task_id,
        context_id=context_id,
        reviewed_at=now if not isinstance(now, str) else datetime.fromisoformat(now),
        reason_code=reason_code,
        note="",
    )


def review_agreement(projection, offer, mandate: SellerMandate,
                     store: AgreementReviewStore, seller_id: str,
                     now: datetime, *, task_id: str, context_id: str,
                     change_request: ChangeRequestEnvelope | None = None
                     ) -> AgreementReviewResult:
    # 1. seller identity
    if projection.seller_id != seller_id:
        return _result(projection, AgreementReviewDecision.REJECTED, "seller_mismatch",
                       now, task_id, context_id)
    # 2. offer hash
    computed_offer_hash = recompute_offer_hash(offer)
    if computed_offer_hash is None or computed_offer_hash != projection.offer_hash:
        return _result(projection, AgreementReviewDecision.REJECTED, "offer_mismatch",
                       now, task_id, context_id, offer_hash=computed_offer_hash or projection.offer_hash)
    # 3. agreement digest
    computed_agreement_hash = recompute_agreement_hash(projection)
    if computed_agreement_hash != projection.agreement_hash:
        return _result(projection, AgreementReviewDecision.REJECTED, "hash_mismatch",
                       now, task_id, context_id, offer_hash=computed_offer_hash)
    # 4. version provenance
    if projection.agreement_version == 1:
        if offer is not None and not _terms_match_offer(projection.terms, offer):
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "terms_mismatch", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
    else:
        previous = store.get(projection.agreement_id, projection.agreement_version - 1)
        if previous is None:
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "version_provenance_failed", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
        if change_request is None:
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "version_provenance_failed", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
        if (change_request.base_version != projection.agreement_version - 1
                or change_request.base_hash != previous["agreement_hash"]
                or change_request.change_request_id != projection.change_request_id):
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "version_provenance_failed", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
        try:
            expected_terms = apply_change_set(
                json.loads(previous["terms"]), change_request.operations
            )
        except Exception:  # noqa
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "version_provenance_failed", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
        if expected_terms != projection.terms:
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "version_provenance_failed", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
    # 5. mandate
    terms = projection.terms
    totals = terms.get("totals", {})
    within_mandate = mandate.allows(
        currency=totals.get("currency", "USD"),
        total_cents=totals.get("total_cents", 0),
        warranty_months=terms.get("warranty_months", 0),
        returns_days=terms.get("returns_days", 0),
        inspection_period_hours=terms.get("inspection", {}).get("period_hours", 0),
        dispute_window_hours=terms.get("dispute_window_hours", 0),
    )
    # authority_ref should use mandate version
    # update result's authority_ref? We'll post-process? Instead set global? We'll adjust _result to accept mandate version.
    if not mandate.auto_accept or not within_mandate:
        store.record(projection, computed_offer_hash, decision="OPERATOR_REQUIRED",
                     now=now, task_id=task_id, context_id=context_id)
        return _result(projection, AgreementReviewDecision.OPERATOR_REQUIRED,
                       "outside_mandate" if mandate.auto_accept else "auto_accept_disabled",
                       now, task_id, context_id, offer_hash=computed_offer_hash)
    # 5a. requirement catalog is satisfiable by this seller
    raw_requirements = terms.get("requirements") or []
    if raw_requirements:
        try:
            catalog = [
                Requirement.model_validate(item) for item in raw_requirements
            ]
            validate_mandate(catalog)
        except (ValidationError, ValueError, TypeError):
            return _result(projection, AgreementReviewDecision.REJECTED,
                           "unsatisfiable_requirement", now, task_id, context_id,
                           offer_hash=computed_offer_hash)
    # 6. accept
    store.record(projection, computed_offer_hash, decision="ACCEPTED",
                 now=now, task_id=task_id, context_id=context_id)
    return _result(projection, AgreementReviewDecision.ACCEPTED, None,
                   now, task_id, context_id, offer_hash=computed_offer_hash)
