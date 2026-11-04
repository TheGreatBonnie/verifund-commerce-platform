from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from verifund_contracts import ReceiptPayload

from verifund_control_plane.domain import canonical_json, sha256_hex


@dataclass(frozen=True)
class SignedReceipt:
    payload: dict[str, Any]
    payload_hash: str
    signature: str
    kid: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def build_receipt_payload(
    *,
    transaction_id: str,
    agreement_hash: str,
    amount_cents: int,
    currency: str,
    buyer_id: str,
    seller_id: str,
    capture_id: str,
    payout_item_id: str,
    evidence_hashes: list[str],
    released_at: datetime,
) -> dict[str, Any]:
    payload = ReceiptPayload(
        transaction_id=transaction_id,
        agreement_hash=agreement_hash,
        amount_cents=amount_cents,
        currency=currency,
        buyer_id=buyer_id,
        seller_id=seller_id,
        capture_id=capture_id,
        payout_item_id=payout_item_id,
        evidence_hashes=evidence_hashes,
        released_at=released_at,
    )
    return payload.model_dump(mode="json")


class ReceiptSigner:
    def __init__(self, keys: dict[str, str], active_kid: str) -> None:
        self._keys = dict(keys)
        self._active_kid = active_kid
        if active_kid not in self._keys:
            raise ValueError("active receipt kid is not configured")

    def _signature(self, kid: str, payload_hash: str) -> str:
        key = self._keys[kid].encode("utf-8")
        digest = hmac.new(
            key, payload_hash.encode("ascii"), hashlib.sha256
        ).digest()
        return _b64url(digest)

    def sign(self, payload: dict[str, Any]) -> SignedReceipt:
        payload_hash = sha256_hex(canonical_json(payload))
        return SignedReceipt(
            payload=payload,
            payload_hash=payload_hash,
            signature=self._signature(self._active_kid, payload_hash),
            kid=self._active_kid,
        )

    def verify(
        self,
        payload: dict[str, Any],
        payload_hash: str,
        signature: str,
        kid: str,
    ) -> bool:
        if kid not in self._keys:
            return False
        actual_hash = sha256_hex(canonical_json(payload))
        if not hmac.compare_digest(actual_hash, payload_hash):
            return False
        expected = self._signature(kid, actual_hash)
        return hmac.compare_digest(expected, signature)
