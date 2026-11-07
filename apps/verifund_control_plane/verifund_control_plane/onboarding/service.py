from __future__ import annotations

from verifund_control_plane.errors import VerifundError

# Spec §9.3: (no profile) -> unverified on onboarding; then:
# unverified -> pending (submit), rejected -> pending (reapply),
# pending -> verified/rejected (admin), verified -> suspended (admin),
# suspended -> verified (reinstate).
SUBMIT_FROM = {"unverified", "rejected"}
DECIDE_MAP = {
    "verified": {"pending", "suspended"},
    "rejected": {"pending"},
    "suspended": {"verified"},
}


async def create_onboarding(store, organization_id: str, actor_user_id: str) -> dict:
    org = await store.get_organization(organization_id)
    if org is None or org["kind"] != "business":
        raise VerifundError(
            "forbidden",
            "seller onboarding requires a business organization",
            status_code=403,
        )
    existing = await store.get_seller_profile_by_organization(organization_id)
    if existing:
        return existing
    seller_id = await store.unique_seller_id(org["slug"] or org["name"])
    profile = await store.upsert_seller_profile(organization_id, seller_id, org["name"])
    await store.upsert_onboarding(organization_id, "in_progress", "profile")
    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type="user",
        action="seller.onboarding.started",
        resource_id=seller_id,
        payload={},
    )
    return profile


async def submit_verification(
    store, organization_id: str, submitted_by: str, documents: list | dict
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    if profile["verification_status"] not in SUBMIT_FROM:
        raise VerifundError("invalid_state", "cannot submit for verification", status_code=409)
    await store.set_verification_status(profile["seller_id"], "pending")
    await store.create_verification(organization_id, submitted_by, documents)
    await store.upsert_onboarding(organization_id, "submitted", "verification")
    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=submitted_by,
        actor_type="user",
        action="seller.verification.submitted",
        resource_id=profile["seller_id"],
        payload={"documents": documents},
    )
    return await store.get_seller_profile(profile["seller_id"])  # type: ignore[return-value]


async def decide_verification(
    store,
    organization_id_or_seller_id: str,
    decision: str,
    note: str | None,
    reviewer_user_id: str,
) -> dict:
    if decision not in DECIDE_MAP:
        raise VerifundError("invalid_state", "invalid decision", status_code=400)
    profile = await store.get_seller_profile_by_organization(
        organization_id_or_seller_id
    )
    if profile is None:
        profile = await store.get_seller_profile(organization_id_or_seller_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    current = profile["verification_status"]
    if current not in DECIDE_MAP[decision]:
        raise VerifundError("invalid_state", "invalid verification transition", status_code=409)
    updated = await store.set_verification_status(
        profile["seller_id"], decision, note=note, reviewer_user_id=reviewer_user_id
    )
    await store.decide_verification_row(
        profile["organization_id"], decision, reviewer_user_id, note
    )
    action = (
        "seller.verification.approved"
        if decision == "verified"
        else "seller.verification.rejected"
        if decision == "rejected"
        else "seller.verification.suspended"
    )
    await store.record_audit(
        scope="organization",
        organization_id=profile["organization_id"],
        actor_user_id=reviewer_user_id,
        actor_type="user",
        action=action,
        resource_id=profile["seller_id"],
        payload={"decision": decision, "note": note},
    )
    return updated  # type: ignore[return-value]


async def save_profile_and_continue(
    store, organization_id: str, actor_user_id: str, display_name: str
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    name = display_name.strip()
    if not name:
        raise VerifundError("invalid_argument", "display_name is required", status_code=400)
    updated_profile = await store.update_seller_display_name(profile["seller_id"], name)
    if updated_profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)

    onboarding = await store.get_onboarding(organization_id)
    current = (onboarding or {}).get("current_step")
    # Do not regress submitted/verified workflows; advance early steps to verification.
    if current in (None, "profile"):
        onboarding = await store.upsert_onboarding(
            organization_id, "in_progress", "verification"
        )
    else:
        onboarding = await store.get_onboarding(organization_id)

    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type="user",
        action="seller.onboarding.profile_saved",
        resource_id=updated_profile["seller_id"],
        payload={"display_name": name},
    )
    return {"profile": updated_profile, "onboarding": onboarding}
