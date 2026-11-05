from __future__ import annotations

from fastapi import APIRouter, Request

from verifund_control_plane.tenancy.identity import require_identity

router = APIRouter()


@router.get("/v1/me")
async def me(request: Request) -> dict:
    identity = await require_identity(request)
    return {
        "user_id": identity.user_id,
        "clerk_user_id": identity.clerk_user_id,
        "tenant_id": identity.tenant_id,
        "clerk_org_id": identity.clerk_org_id,
        "role": identity.role,
        "permissions": sorted(identity.permissions),
        "is_platform_admin": identity.is_platform_admin,
        "organization_status": identity.organization_status,
    }
