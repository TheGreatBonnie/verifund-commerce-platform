from __future__ import annotations

import secrets

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import decide_verification
from verifund_control_plane.tenancy.identity import (
    SYSTEM_IDENTITY,
    Identity,
    require_identity,
)

router = APIRouter()


class VerificationDecision(BaseModel):
    decision: str = Field(pattern="^(verified|rejected|suspended)$")
    note: str | None = None


async def require_platform_admin(request: Request) -> Identity:
    provided = request.headers.get("authorization", "")
    if provided.startswith("Bearer ") and secrets.compare_digest(
        provided.removeprefix("Bearer "), request.app.state.settings.ops_token
    ):
        return SYSTEM_IDENTITY
    identity = await require_identity(request)
    if not identity.is_platform_admin:
        raise VerifundError("forbidden", "platform admin required", status_code=403)
    return identity


@router.post("/ops/sellers/{seller_id}/verification")
async def ops_verification(
    seller_id: str, body: VerificationDecision, request: Request
) -> dict:
    identity = await require_platform_admin(request)
    store = request.app.state.tenancy
    updated = await decide_verification(
        store, seller_id, body.decision, body.note, identity.user_id
    )
    return updated


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
