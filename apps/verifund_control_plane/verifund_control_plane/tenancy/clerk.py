from __future__ import annotations

import asyncio
from typing import Protocol

from clerk_backend_api import Clerk


class ClerkDirectory(Protocol):
    async def user(self, clerk_user_id: str) -> dict | None: ...
    async def organization(self, clerk_org_id: str) -> dict | None: ...
    async def membership(
        self, clerk_org_id: str, clerk_user_id: str
    ) -> dict | None: ...


class ClerkBackendDirectory:
    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key
        self._sdk = Clerk(bearer_auth=secret_key)

    async def user(self, clerk_user_id: str) -> dict | None:
        user = await asyncio.to_thread(self._sdk.users.get, user_id=clerk_user_id)
        if user is None:
            return None
        email = (
            user.email_addresses[0].email_address if user.email_addresses else None
        )
        name = " ".join(filter(None, [user.first_name, user.last_name])) or None
        return {"id": user.id, "email": email, "name": name}

    async def organization(self, clerk_org_id: str) -> dict | None:
        org = await asyncio.to_thread(
            self._sdk.organizations.get, organization_id=clerk_org_id
        )
        if org is None:
            return None
        return {
            "id": org.id,
            "name": org.name,
            "slug": getattr(org, "slug", None),
        }

    async def membership(
        self, clerk_org_id: str, clerk_user_id: str
    ) -> dict | None:
        memberships = await asyncio.to_thread(
            self._sdk.organizations.list_memberships,
            organization_id=clerk_org_id,
            user_id=clerk_user_id,
        )
        if not memberships:
            return None
        membership = memberships[0]
        return {
            "organization": {"id": clerk_org_id},
            "public_user_data": {"user_id": clerk_user_id},
            "role": membership.role,
        }
