from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .models import ApprovalTokenRecord


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


class ApprovalTokenService:
    def __init__(self, secret: str, *, ttl_minutes: int = 30,
                 clock: Callable[[], datetime] | None = None):
        self.secret = secret.encode("utf-8")
        self.ttl_minutes = ttl_minutes
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self.clock()

    def issue(self, agreement_id: str, version: int, agreement_hash: str,
              subject_id: str, issued_by_actor_type: str,
              issued_by_actor_id: str, now: datetime,
              *, agreement_expires_at: datetime | None = None
              ) -> tuple[str, ApprovalTokenRecord]:
        jti = str(uuid.uuid4())
        ttl = timedelta(minutes=self.ttl_minutes)
        exp = now + ttl
        if agreement_expires_at is not None:
            exp = min(exp, agreement_expires_at)
        claims = {
            "jti": jti, "aud": "agreement-approval", "sub": subject_id,
            "agreement_id": agreement_id, "version": version,
            "agreement_hash": agreement_hash,
            "iat": now.isoformat().replace("+00:00", "Z"),
            "exp": exp.isoformat().replace("+00:00", "Z"),
        }
        raw = _b64url_encode(json.dumps(claims, sort_keys=True).encode()) + "." + _b64url_encode(
            hmac.new(self.secret, json.dumps(claims, sort_keys=True).encode(), hashlib.sha256).digest()
        )
        record = ApprovalTokenRecord(
            jti=jti, agreement_id=agreement_id, version=version,
            agreement_hash=agreement_hash, subject_id=subject_id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            issued_at=now, expires_at=exp,
            issued_by_actor_type=issued_by_actor_type,
            issued_by_actor_id=issued_by_actor_id,
        )
        return raw, record

    def verify(self, raw: str) -> dict[str, Any]:
        try:
            body, sig = raw.split(".", 1)
        except ValueError:
            raise ValueError("invalid_token")
        claims_json = _b64url_decode(body)
        claims = json.loads(claims_json)
        expected_sig = hmac.new(self.secret, claims_json, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected_sig):
            raise ValueError("invalid_signature")
        now = self._now()
        exp = datetime.fromisoformat(claims["exp"].replace("Z", "+00:00"))
        if now > exp:
            raise ValueError("token_expired")
        if claims.get("aud") != "agreement-approval":
            raise ValueError("invalid_audience")
        return claims

    @staticmethod
    def token_hash(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def consume(self, repo, conn, raw: str, jti: str,
                      decision_id: str, now: datetime) -> bool:
        record = await repo.get_token(jti)
        if record is None or record.token_hash != self.token_hash(raw):
            return False
        return await repo.consume_token(conn, jti, now, decision_id)
