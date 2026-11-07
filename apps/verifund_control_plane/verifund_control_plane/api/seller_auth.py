from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Request

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import require_identity


@dataclass(frozen=True)
class SellerPrincipal:
    seller_id: str
    organization_id: str
    actor: str
    auth_kind: Literal["clerk", "internal_service"]
    scopes: frozenset[str]


_INTERNAL_SCOPES = frozenset({"txn:read", "evidence:write"})


def _constant_time_eq(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _expected_internal_token(settings: Any) -> str | None:
    return getattr(settings, "settlement_internal_token", None) or getattr(
        settings, "seller_internal_token", None
    )


async def _principal_for_org(
    store: Any,
    organization_id: str,
    *,
    actor: str,
    auth_kind: Literal["clerk", "internal_service"],
    scopes: frozenset[str],
) -> SellerPrincipal:
    org = await store.get_organization(organization_id)
    if org is None:
        raise VerifundError("forbidden", "seller access denied", status_code=403)
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("forbidden", "seller access denied", status_code=403)
    return SellerPrincipal(
        seller_id=profile["seller_id"],
        organization_id=organization_id,
        actor=actor,
        auth_kind=auth_kind,
        scopes=scopes,
    )


async def resolve_seller_principal(request: Request, *, required_scope: str) -> SellerPrincipal:
    settings = request.app.state.settings
    internal = request.headers.get("x-verifund-internal-token")
    if internal is not None:
        if not _constant_time_eq(internal, _expected_internal_token(settings)):
            raise VerifundError("unauthorized", "seller access is required", status_code=401)
        org_id = request.headers.get("x-seller-org-id")
        if not org_id:
            seller_id = request.headers.get("x-seller-id")
            if seller_id:
                profile = await request.app.state.tenancy.get_seller_profile(seller_id)
                if profile is not None:
                    org_id = profile.get("organization_id")
        if not org_id:
            raise VerifundError("unauthorized", "seller access is required", status_code=401)
        principal = await _principal_for_org(
            request.app.state.tenancy,
            org_id,
            actor="service:settlement",
            auth_kind="internal_service",
            scopes=_INTERNAL_SCOPES,
        )
        header_seller = request.headers.get("x-seller-id")
        if header_seller and header_seller != principal.seller_id:
            raise VerifundError("forbidden", "seller access denied", status_code=403)
        if required_scope and required_scope not in principal.scopes:
            raise VerifundError("forbidden", "insufficient scope", status_code=403)
        return principal

    identity = await require_identity(request)
    scopes = {"txn:read"}
    if required_scope == "evidence:write":
        scopes.add("evidence:write")
    principal = await _principal_for_org(
        request.app.state.tenancy,
        identity.tenant_id,
        actor=f"user:{identity.user_id}",
        auth_kind="clerk",
        scopes=frozenset(scopes),
    )
    if required_scope and required_scope not in principal.scopes:
        raise VerifundError("forbidden", "insufficient scope", status_code=403)
    return principal


def seller_owns_transaction(principal: SellerPrincipal, record: Any) -> bool:
    if getattr(record, "seller_id", None) == principal.seller_id:
        return True
    org_id = getattr(record, "seller_organization_id", None)
    return bool(org_id and org_id == principal.organization_id)


async def authorize_seller_transaction(
    request: Request, transaction_id: str, *, required_scope: str
) -> tuple[SellerPrincipal, Any]:
    principal = await resolve_seller_principal(request, required_scope=required_scope)
    try:
        record = await request.app.state.repo.get_transaction(transaction_id)
    except VerifundError:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    if record is None or not seller_owns_transaction(principal, record):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return principal, record
