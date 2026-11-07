from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Request

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import require_identity


@dataclass(frozen=True)
class BuyerPrincipal:
    buyer_id: str
    organization_id: str
    actor: str
    auth_kind: Literal["clerk", "internal_service"]
    scopes: frozenset[str]


_INTERNAL_SCOPES = frozenset({"txn:read", "txn:act", "agreement:decide"})


def _constant_time_eq(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


async def _principal_for_org(
    store: Any,
    organization_id: str,
    *,
    actor: str,
    auth_kind: Literal["clerk", "internal_service"],
    scopes: frozenset[str],
) -> BuyerPrincipal:
    profile = await store.get_buyer_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("forbidden", "buyer access denied", status_code=403)
    return BuyerPrincipal(
        buyer_id=profile["buyer_id"],
        organization_id=organization_id,
        actor=actor,
        auth_kind=auth_kind,
        scopes=scopes,
    )


async def resolve_buyer_principal(request: Request, *, required_scope: str) -> BuyerPrincipal:
    settings = request.app.state.settings
    internal = request.headers.get("x-verifund-buyer-internal-token")
    if internal is not None:
        if not _constant_time_eq(
            internal, getattr(settings, "buyer_settlement_internal_token", None)
        ):
            raise VerifundError(
                "unauthorized", "buyer access is required", status_code=401
            )
        org_id = request.headers.get("x-buyer-org-id")
        if not org_id:
            buyer_id = request.headers.get("x-buyer-id")
            if buyer_id:
                profile = await request.app.state.tenancy.get_buyer_profile(buyer_id)
                if profile is not None:
                    org_id = profile.get("organization_id")
        if not org_id:
            raise VerifundError(
                "unauthorized", "buyer access is required", status_code=401
            )
        principal = await _principal_for_org(
            request.app.state.tenancy,
            org_id,
            actor="service:buyer-settlement",
            auth_kind="internal_service",
            scopes=_INTERNAL_SCOPES,
        )
        header_buyer = request.headers.get("x-buyer-id")
        if header_buyer and header_buyer != principal.buyer_id:
            raise VerifundError("forbidden", "buyer access denied", status_code=403)
        if required_scope and required_scope not in principal.scopes:
            raise VerifundError("forbidden", "insufficient scope", status_code=403)
        # Agreement ownership check happens where we have an agreement; txn authz helpers below cover transactions.
        return principal

    identity = await require_identity(request)
    # Clerk scope mapping: mirror buyer permissions. org:buyer has txn read/approve + evidence read in tenancy/permissions.
    # Grant read always; grant act/decide only when capability is present in identity permissions or role indicates buyer.
    scopes = {"txn:read"}
    # identity.permissions is a frozenset of org:* strings; map to our scopes defensively.
    permissions = getattr(identity, "permissions", frozenset()) or frozenset()
    role = getattr(identity, "role", "") or ""
    has_act = (
        "org:transactions:approve" in permissions
        or role in {"org:buyer", "org:admin", "org:owner"}
        or "org:transactions:approve" in str(permissions)
    )
    if has_act:
        scopes.update({"txn:act", "agreement:decide"})
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


def buyer_owns_transaction(principal: BuyerPrincipal, record: Any) -> bool:
    if getattr(record, "buyer_id", None) == principal.buyer_id:
        return True
    org_id = getattr(record, "buyer_organization_id", None)
    return bool(org_id and org_id == principal.organization_id)


async def authorize_buyer_transaction(
    request: Request, transaction_id: str, *, required_scope: str
) -> tuple[BuyerPrincipal, Any]:
    principal = await resolve_buyer_principal(request, required_scope=required_scope)
    try:
        record = await request.app.state.repo.get_transaction(transaction_id)
    except VerifundError:
        raise VerifundError("not_found", "transaction not found", status_code=404) from None
    if record is None or not buyer_owns_transaction(principal, record):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return principal, record


def buyer_owns_agreement(principal: BuyerPrincipal, agreement: Any) -> bool:
    if getattr(agreement, "buyer_id", None) == principal.buyer_id:
        return True
    # If agreement carries org hint, allow org match (defensive; buyer_id is primary).
    org_id = getattr(agreement, "buyer_organization_id", None)
    return bool(org_id and org_id == principal.organization_id)


async def authorize_buyer_agreement(
    request: Request, agreement: Any, *, required_scope: str
) -> BuyerPrincipal:
    principal = await resolve_buyer_principal(request, required_scope=required_scope)
    if agreement is None or not buyer_owns_agreement(principal, agreement):
        raise VerifundError("not_found", "agreement not found", status_code=404)
    return principal
