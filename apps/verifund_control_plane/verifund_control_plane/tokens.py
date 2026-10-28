from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from verifund_control_plane.domain import canonical_json, sha256_hex
from verifund_control_plane.errors import VerifundError


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class SellerClaims:
    txn: str
    seller_id: str
    agreement_hash: str
    scopes: tuple[str, ...]
    jti: str
    jti_hash: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    jti_hash: str
    expires_at: datetime


class SellerTokenService:
    def __init__(
        self,
        secret: str,
        *,
        ttl_hours: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl = timedelta(hours=ttl_hours)
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(
        self,
        transaction_id: str,
        seller_id: str,
        agreement_hash: str,
        *,
        scopes: tuple[str, ...] | list[str] = (
            "txn:read",
            "evidence:write",
        ),
    ) -> IssuedToken:
        now = self._clock()
        expires = now + self._ttl
        jti = secrets.token_urlsafe(24)
        claims = {
            "typ": "seller_txn",
            "txn": transaction_id,
            "seller_id": seller_id,
            "agreement_hash": agreement_hash,
            "scope": list(scopes),
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": jti,
        }
        body = _b64url(canonical_json(claims))
        signature = _b64url(
            hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        )
        return IssuedToken(
            token=f"v1.{body}.{signature}",
            jti=jti,
            jti_hash=sha256_hex(jti.encode("utf-8")),
            expires_at=expires,
        )

    def verify(
        self, token: str, *, required_scope: str | None = None
    ) -> SellerClaims:
        try:
            version, body, signature = token.split(".")
            if version != "v1":
                raise ValueError("unsupported token version")
            expected = _b64url(
                hmac.new(
                    self._secret,
                    body.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            claims: dict[str, Any] = json.loads(_unb64url(body))
            if claims.get("typ") != "seller_txn":
                raise ValueError("wrong token type")
            issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise VerifundError(
                "unauthorized", "seller token is invalid", status_code=401
            ) from exc
        if expires_at <= self._clock():
            raise VerifundError(
                "token_expired", "seller token has expired", status_code=401
            )
        scopes = tuple(claims.get("scope", ()))
        if required_scope is not None and required_scope not in scopes:
            raise VerifundError(
                "token_scope_denied",
                "seller token scope denied",
                status_code=403,
            )
        jti = str(claims["jti"])
        return SellerClaims(
            txn=str(claims["txn"]),
            seller_id=str(claims["seller_id"]),
            agreement_hash=str(claims["agreement_hash"]),
            scopes=scopes,
            jti=jti,
            jti_hash=sha256_hex(jti.encode("utf-8")),
            issued_at=issued_at,
            expires_at=expires_at,
        )


@dataclass(frozen=True)
class LinkClaims:
    kind: str
    transaction_id: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedLink:
    token: str
    jti: str
    expires_at: datetime


class LinkSigner:
    def __init__(
        self,
        secret: str,
        *,
        checkout_ttl_minutes: int,
        return_ttl_hours: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret = secret.encode("utf-8")
        self._checkout_ttl = timedelta(minutes=checkout_ttl_minutes)
        self._return_ttl = timedelta(hours=return_ttl_hours)
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(self, kind: str, transaction_id: str) -> IssuedLink:
        if kind not in {"checkout", "return", "cancel"}:
            raise ValueError(f"unsupported link kind: {kind}")
        now = self._clock()
        ttl = self._checkout_ttl if kind == "checkout" else self._return_ttl
        expires = now + ttl
        jti = secrets.token_urlsafe(24)
        claims = {
            "typ": kind,
            "txn": transaction_id,
            "exp": int(expires.timestamp()),
            "jti": jti,
        }
        body = _b64url(canonical_json(claims))
        signature = _b64url(
            hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        )
        return IssuedLink(
            token=f"v1.{body}.{signature}", jti=jti, expires_at=expires
        )

    def verify(self, token: str, *, expected_kind: str) -> LinkClaims:
        try:
            version, body, signature = token.split(".")
            if version != "v1":
                raise ValueError("unsupported token version")
            expected = _b64url(
                hmac.new(
                    self._secret,
                    body.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            claims: dict[str, Any] = json.loads(_unb64url(body))
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise VerifundError(
                "unauthorized", "link is invalid", status_code=401
            ) from exc
        if claims.get("typ") != expected_kind:
            raise VerifundError(
                "forbidden", "link kind mismatch", status_code=403
            )
        if expires_at <= self._clock():
            raise VerifundError(
                "token_expired", "link has expired", status_code=401
            )
        return LinkClaims(
            kind=expected_kind,
            transaction_id=str(claims["txn"]),
            jti=str(claims["jti"]),
            expires_at=expires_at,
        )
