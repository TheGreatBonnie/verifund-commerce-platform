from __future__ import annotations

from sqlalchemy import update

from verifund_control_plane.errors import VerifundError


def clerk_buyer_headers(
    app,
    *,
    sub="user_buyer",
    org_id=None,
    org_role="org:buyer",
    token="buyer-bearer",
):
    mappings = getattr(app.state, "_test_clerk_mappings", None)
    if mappings is None:
        mappings = {}
        app.state._test_clerk_mappings = mappings

        def _auth(request):
            header = request.headers.get("authorization", "")
            token_value = (
                header.removeprefix("Bearer ").strip()
                if header.startswith("Bearer ")
                else ""
            )
            claims = mappings.get(token_value) or mappings.get("*")
            if claims is None:
                raise VerifundError(
                    "unauthorized", "sign-in required", status_code=401
                )
            return claims

        app.state.clerk_authenticator = _auth
    mappings[token] = {"sub": sub, "org_id": org_id, "org_role": org_role}
    return {"authorization": f"Bearer {token}"}


async def _ensure_org_clerk_id(store, organization_id: str, clerk_org_id: str) -> None:
    async with store.engine.begin() as conn:
        await conn.execute(
            update(store.organizations)
            .where(store.organizations.c.id == organization_id)
            .values(clerk_org_id=clerk_org_id)
        )


async def seed_buyer_profile(
    app,
    *,
    clerk_org_id=None,
    buyer_id,
    display_name=None,
    clerk_user_id="user_buyer",
):
    store = app.state.tenancy
    user = await store.upsert_user(
        clerk_user_id, f"{clerk_user_id}@example.com", display_name or buyer_id
    )
    # Ensure a personal org exists for tenancy/backfill compat, but buyer identity
    # is now keyed directly by clerk_user_id, not organization_id.
    org = await store.ensure_personal_organization(user["id"])
    organization_id = org["id"]
    await store.upsert_buyer_profile(organization_id, buyer_id, clerk_user_id=clerk_user_id)
    await store.upsert_membership(
        organization_id, user["id"], "org:buyer", f"mem_{clerk_user_id}_{buyer_id}"
    )
    profile = await store.get_buyer_profile(buyer_id)
    return {
        "user": user,
        "org": org,
        "profile": profile,
    }


def internal_buyer_headers(
    *, token="buyer-internal-secret", clerk_user_id: str, buyer_id: str | None = None
):
    headers = {
        "x-verifund-buyer-internal-token": token,
        "x-buyer-clerk-user-id": clerk_user_id,
    }
    if buyer_id:
        headers["x-buyer-id"] = buyer_id
    return headers
