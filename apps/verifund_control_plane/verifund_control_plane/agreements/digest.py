from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def agreement_hash(agreement_id: str, version: int, terms: dict[str, Any]) -> str:
    payload = {
        "schema": "verifund.agreement.v1",
        "agreement_id": agreement_id,
        "version": version,
        "agreement_type": terms.get("agreement_type", "goods"),
        "terms_version": terms.get("terms_version", 1),
        "terms": terms,
    }
    return sha256_hex(canonical_json(payload))
