from __future__ import annotations

from sqlalchemy import update


def clerk_seller_headers(
    app, *, sub="user_seller", org_id="org_seller", org_role="org:admin", token="seller-bearer"
):
    """Configure app for Clerk-authenticated seller requests and return headers.

    Supports multiple identities by mapping bearer token -> Clerk claims.
    """
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
                raise RuntimeError(f"no test Clerk mapping for token {token_value!r}")
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


async def seed_seller_profile(
    app,
    *,
    clerk_org_id,
    seller_id,
    display_name,
    clerk_user_id="user_seller",
):
    """Ensure org/user/membership/seller profile exist for Clerk seller auth tests.

    Compatible with auto-provisioned seller profiles created by award flows.
    """
    store = app.state.tenancy
    user = await store.upsert_user(clerk_user_id, f"{clerk_user_id}@example.com", display_name)

    existing_profile = await store.get_seller_profile(seller_id)
    if existing_profile is not None:
        organization_id = existing_profile["organization_id"]
        await _ensure_org_clerk_id(store, organization_id, clerk_org_id)
        org = await store.get_organization(organization_id)
    else:
        org = await store.upsert_organization(clerk_org_id, display_name, clerk_org_id)
        organization_id = org["id"]
        existing_profile = await store.upsert_seller_profile(
            organization_id, seller_id, display_name
        )

    await store.upsert_membership(
        organization_id, user["id"], "org:admin", f"mem_{clerk_user_id}_{seller_id}"
    )
    profile = await store.get_seller_profile(seller_id)
    return {"user": user, "org": org or await store.get_organization(organization_id), "profile": profile}


def internal_seller_headers(
    *, token="secret", organization_id: str, seller_id: str | None = None
):
    headers = {"x-verifund-internal-token": token, "x-seller-org-id": organization_id}
    if seller_id:
        headers["x-seller-id"] = seller_id
    return headers
