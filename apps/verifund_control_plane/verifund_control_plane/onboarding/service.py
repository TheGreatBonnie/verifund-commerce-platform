from __future__ import annotations

from verifund_control_plane.errors import VerifundError

STEP_ORDER = ["profile", "agent", "config", "catalog", "test", "verification", "activation"]


async def require_step(store, organization_id: str, required: str) -> dict:
    """Enforce strict onboarding order. Legacy seeded profile w/o row is allowed."""
    onboarding = await store.get_onboarding(organization_id)
    if onboarding is None:
        profile = await store.get_seller_profile_by_organization(organization_id)
        if profile is None:
            raise VerifundError(
                "onboarding_incomplete",
                f"onboarding step {required!r} requires profile complete",
                status_code=409,
                details={"current_step": None, "missing": "profile"},
            )
        return {}
    current = onboarding.get("current_step")
    idx = STEP_ORDER.index(current) if current in STEP_ORDER else -1
    if idx < STEP_ORDER.index(required):
        raise VerifundError(
            "onboarding_incomplete",
            f"onboarding step {required!r} requires step {current!r} complete",
            status_code=409,
            details={"current_step": current, "missing": required},
        )
    return onboarding


async def advance_step(store, organization_id: str, next_step: str) -> dict:
    onboarding = await store.get_onboarding(organization_id)
    if onboarding is None:
        return {}
    current = onboarding.get("current_step")
    if current in STEP_ORDER and STEP_ORDER.index(next_step) > STEP_ORDER.index(current):
        return await store.upsert_onboarding(organization_id, "in_progress", next_step)
    return onboarding

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
    import uuid
    seller_id = uuid.uuid4().hex
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
    store, organization_id: str, submitted_by: str, documents: list | dict,
    *, payout_email: str = "", auto_approve_sandbox: bool = False,
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    if profile["verification_status"] not in SUBMIT_FROM:
        raise VerifundError("invalid_state", "cannot submit for verification", status_code=409)
    if not payout_email.strip():
        raise VerifundError("invalid_argument", "payout_email is required", status_code=422)
    # Persist payout_email alongside documents for the review/approve step.
    stored_documents = dict(documents) if isinstance(documents, dict) else {"items": documents}
    stored_documents["payout_email"] = payout_email.strip()
    await store.set_verification_status(profile["seller_id"], "pending")
    await store.create_verification(organization_id, submitted_by, stored_documents)
    await store.upsert_onboarding(organization_id, "submitted", "verification")
    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=submitted_by,
        actor_type="user",
        action="seller.verification.submitted",
        resource_id=profile["seller_id"],
        payload={"documents": stored_documents},
    )
    if auto_approve_sandbox:
        approved = await decide_verification(
            store,
            organization_id,
            decision="verified",
            note="Auto-approved in sandbox",
            reviewer_user_id=submitted_by,
        )
        await store.upsert_onboarding(organization_id, "in_progress", "activation")
        return approved
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
    if decision == "verified":
        try:
            from sqlalchemy import select as _select
            async with store.engine.connect() as _conn:
                _res = await _conn.execute(
                    _select(store.seller_verifications).order_by(
                        store.seller_verifications.c.id.desc()
                    )
                )
                for _row in _res.fetchall():
                    _docs = _row._mapping.get("documents") or {}
                    if isinstance(_docs, dict) and _docs.get("payout_email"):
                        await store.upsert_payment_account(
                            organization_id=profile["organization_id"],
                            provider="paypal",
                            provider_account_id=str(_docs["payout_email"]),
                            account_type="payout",
                            status="active",
                            credentials_reference=f"secret:{profile['seller_id']}",
                        )
                        break
        except Exception:  # noqa: BLE001 - payout write must not block verification
            pass
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
    # Advance early steps to agent (strict sequence); never regress later steps.
    if current in (None, "profile"):
        onboarding = await store.upsert_onboarding(
            organization_id, "in_progress", "agent"
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
