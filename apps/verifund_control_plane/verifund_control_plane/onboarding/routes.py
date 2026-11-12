from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    save_profile_and_continue,
    submit_verification,
)
from verifund_control_plane.tenancy.identity import require_identity

router = APIRouter()


class VerificationSubmit(BaseModel):
    documents: list | dict = Field(default_factory=list)
    payout_email: str = Field(min_length=3, max_length=254)


class ProfileSave(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)


@router.post("/v1/seller/onboarding", status_code=201)
async def start_onboarding(request: Request, response: Response) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    org = await store.get_organization(identity.tenant_id)
    if org is None or org["kind"] != "business":
        raise VerifundError(
            "forbidden", "seller onboarding requires a business organization", status_code=403
        )
    existing = await store.get_seller_profile_by_organization(identity.tenant_id)
    profile = await create_onboarding(store, identity.tenant_id, identity.user_id)
    onboarding = await store.get_onboarding(identity.tenant_id)
    if existing is not None:
        response.status_code = 200
    return {"profile": profile, "onboarding": onboarding}


@router.get("/v1/seller/onboarding")
async def get_onboarding(request: Request) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    onboarding = await store.get_onboarding(identity.tenant_id)
    if profile is None and onboarding is None:
        raise VerifundError("not_found", "seller onboarding not found", status_code=404)
    return {"profile": profile, "onboarding": onboarding}


@router.post("/v1/seller/onboarding/profile")
async def save_profile(request: Request, body: ProfileSave) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    return await save_profile_and_continue(
        store, identity.tenant_id, identity.user_id, body.display_name
    )


@router.post("/v1/seller/verification/submit")
async def submit(request: Request, body: VerificationSubmit) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    settings = request.app.state.settings
    return await submit_verification(
        store,
        identity.tenant_id,
        identity.user_id,
        body.documents,
        payout_email=body.payout_email,
        auto_approve_sandbox=bool(
            getattr(settings, "verifund_auto_verify", False)
            or getattr(settings, "is_sandbox", False)
        ),
    )
