from __future__ import annotations

from dataclasses import dataclass

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import Request

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.permissions import ROLE_PERMISSIONS


@dataclass(frozen=True)
class Identity:
    user_id: str
    clerk_user_id: str
    tenant_id: str
    clerk_org_id: str | None
    role: str
    permissions: frozenset[str]
    is_platform_admin: bool
    organization_status: str


def _identity(
    user: dict, org: dict, role: str, settings, is_platform_admin: bool
) -> Identity:
    return Identity(
        user_id=user["id"],
        clerk_user_id=user["clerk_user_id"],
        tenant_id=org["id"],
        clerk_org_id=org.get("clerk_org_id"),
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["org:member"]),
        is_platform_admin=is_platform_admin,
        organization_status=org["status"],
    )


async def resolve_identity(store, payload: dict, settings, directory=None) -> Identity:
    if directory is None:
        directory = getattr(settings, "clerk_directory", None)
    if directory is None:
        directory = getattr(settings, "_clerk_directory", None)
    user = await store.get_user_by_clerk_id(payload["sub"])
    if user is None:
        if directory is None:
            email = payload.get("email") or f"{payload['sub']}@clerk.local"
            user = await store.upsert_user(payload["sub"], email, payload.get("name"))
        else:
            remote = await directory.user(payload["sub"])
            if remote is None:
                raise VerifundError("unauthorized", "unknown user", status_code=401)
            user = await store.upsert_user(
                remote["id"], remote.get("email"), remote.get("name")
            )

    clerk_org_id = payload.get("org_id")
    if not clerk_org_id:
        org = await store.ensure_personal_organization(user["id"])
        return _identity(
            user, org, "org:buyer", settings, await store.is_platform_admin(user["id"])
        )

    org = await store.get_organization_by_clerk_id(clerk_org_id)
    if org is None:
        if directory is None:
            raise VerifundError(
                "forbidden", "organization membership required", status_code=403
            )
        remote_org = await directory.organization(clerk_org_id)
        if remote_org is None:
            raise VerifundError("forbidden", "unknown organization", status_code=403)
        org = await store.upsert_organization(
            remote_org["id"], remote_org["name"], remote_org.get("slug")
        )
    membership = await store.get_membership(org["id"], user["id"])
    if membership is None or membership["status"] != "active":
        if directory is None:
            raise VerifundError(
                "forbidden", "organization membership required", status_code=403
            )
        remote = await directory.membership(clerk_org_id, payload["sub"])
        if remote is None:
            raise VerifundError("forbidden", "not a member", status_code=403)
        # upsert_membership_from_clerk needs local user+org; both exist now
        membership = await store.upsert_membership_from_clerk(remote)
        if membership is None:
            raise VerifundError("forbidden", "not a member", status_code=403)
    if org["status"] != "active":
        raise VerifundError(
            "forbidden", "organization is not active", status_code=403
        )
    return _identity(
        user, org, membership["role"], settings, await store.is_platform_admin(user["id"])
    )


def _default_authenticator(request: Request, settings) -> dict:
    try:
        state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=settings.clerk_secret_key,
                jwt_key=settings.clerk_jwt_key,
                authorized_parties=[settings.console_base_url],
                accepts_token=["session_token"],
            ),
        )
    except Exception as exc:
        raise VerifundError("unauthorized", "sign-in required", status_code=401) from exc
    if not getattr(state, "is_signed_in", False):
        raise VerifundError("unauthorized", "sign-in required", status_code=401)
    # clerk-backend-api 4.x returns a VerifyTokenResponse with claims dict
    payload = getattr(state, "payload", None) or getattr(state, "claims", None) or {}
    # Some versions expose raw claims via .payload; fall back to empty dict
    # so resolve_identity raises a clear 401/403 rather than AttributeError.
    if not isinstance(payload, dict):
        try:
            payload = dict(payload)
        except Exception:
            payload = {}
    return payload


async def require_identity(request: Request) -> Identity:
    authenticator = getattr(request.app.state, "clerk_authenticator", None)
    payload = (
        authenticator(request)
        if authenticator is not None
        else _default_authenticator(request, request.app.state.settings)
    )
    return await resolve_identity(
        request.app.state.tenancy, payload, request.app.state.settings
    )


SYSTEM_IDENTITY = Identity(
    user_id="system",
    clerk_user_id="system",
    tenant_id="",
    clerk_org_id=None,
    role="system",
    permissions=frozenset({"*"}),
    is_platform_admin=True,
    organization_status="active",
)
