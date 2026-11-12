from __future__ import annotations

from typing import Any

from verifund_contracts.models import canonical_json, sha256_hex

__all__ = ["agreement_hash", "canonical_json", "sha256_hex"]


def agreement_hash(agreement_id: str, version: int, terms: dict[str, Any]) -> str:
    totals = terms.get("totals", {}) if isinstance(terms, dict) else {}
    payload = {
        "schema": "verifund.agreement.v1",
        "agreement_id": agreement_id,
        "version": version,
        "agreement_type": terms.get("agreement_type", "goods") if isinstance(terms, dict) else "goods",
        "terms_version": terms.get("terms_version", 1) if isinstance(terms, dict) else 1,
        "terms": terms,
        "amount_cents": totals.get("total_cents", 0),
        "shipping_cents": totals.get("shipping_cents", 0),
        "tax_cents": totals.get("tax_cents", 0),
        "fees_cents": totals.get("fees_cents", 0),
        "total_cents": totals.get("total_cents", 0),
        "offer_id": terms.get("offer", {}).get("offer_id", "") if isinstance(terms, dict) else "",
        "offer_round": terms.get("offer", {}).get("offer_round", 1) if isinstance(terms, dict) else 1,
        "offer_hash": terms.get("offer", {}).get("offer_hash", "") if isinstance(terms, dict) else "",
    }
    return sha256_hex(canonical_json(payload))
