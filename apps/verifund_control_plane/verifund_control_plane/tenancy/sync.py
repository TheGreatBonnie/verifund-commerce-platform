from __future__ import annotations


async def apply_clerk_event(store, event: dict) -> None:
    kind = event["type"]
    data = event.get("data") or {}
    if kind in {"user.created", "user.updated"}:
        await store.upsert_user(
            data["id"],
            (data.get("email_addresses") or [{}])[0].get("email_address"),
            " ".join(filter(None, [data.get("first_name"), data.get("last_name")])) or None,
        )
    elif kind == "user.deleted":
        await store.anonymize_user(data["id"])
    elif kind == "organization.created":
        await store.upsert_organization(data["id"], data.get("name", ""), data.get("slug"))
    elif kind == "organization.updated":
        await store.update_organization(data["id"], data.get("name"), data.get("slug"))
    elif kind == "organization.deleted":
        await store.set_organization_status_by_clerk_id(data["id"], "disabled")
    elif kind == "organizationMembership.created":
        await store.upsert_membership_from_clerk(data)
    elif kind == "organizationMembership.updated":
        await store.upsert_membership_from_clerk(data)
    elif kind == "organizationMembership.deleted":
        await store.remove_membership_from_clerk(data)
    elif kind == "organizationInvitation.created":
        await store.upsert_invitation_from_clerk(data)
    elif kind == "organizationInvitation.revoked":
        await store.revoke_invitation_from_clerk(data)
