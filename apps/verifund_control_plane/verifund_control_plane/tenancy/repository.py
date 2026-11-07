from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, MetaData, String, Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from verifund_control_plane.db import configure_sqlite


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id() -> str:
    return str(uuid4())


class TenancyRepository:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self._repo: Any = None
        self._org_id: str | None = None
        self._define_tables()

    def _define_tables(self) -> None:
        self.users = Table(
            "users",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("clerk_user_id", String, unique=True, nullable=False),
            Column("email", String),
            Column("name", String),
            Column("status", String, nullable=False, default="active"),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.organizations = Table(
            "organizations",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("clerk_org_id", String, unique=True),
            Column("kind", String, nullable=False),
            Column("name", String, nullable=False),
            Column("slug", String, unique=True),
            Column("status", String, nullable=False, default="active"),
            Column("owner_user_id", String),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.organization_members = Table(
            "organization_members",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("user_id", String, nullable=False, index=True),
            Column("role", String, nullable=False),
            Column("status", String, nullable=False, default="active"),
            Column("clerk_membership_id", String, unique=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.platform_admins = Table(
            "platform_admins",
            self.metadata,
            Column("user_id", String, primary_key=True),
            Column("granted_by", String),
            Column("created_at", String, nullable=False),
        )
        self.seller_profiles = Table(
            "seller_profiles",
            self.metadata,
            Column("seller_id", String, primary_key=True),
            Column("organization_id", String, unique=True, nullable=False),
            Column("display_name", String, nullable=False),
            Column("verification_status", String, nullable=False, default="unverified"),
            Column("verification_note", String),
            Column("verified_at", String),
            Column("verified_by", String),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.buyer_profiles = Table(
            "buyer_profiles",
            self.metadata,
            Column("buyer_id", String, primary_key=True),
            Column("organization_id", String, unique=True, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.organization_invitations = Table(
            "organization_invitations",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("clerk_invitation_id", String, unique=True),
            Column("email", String, nullable=False),
            Column("role", String, nullable=False),
            Column("status", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.seller_onboarding = Table(
            "seller_onboarding",
            self.metadata,
            Column("organization_id", String, primary_key=True),
            Column("status", String, nullable=False),
            Column("current_step", String, nullable=False),
            Column("completed_steps", JSON, nullable=False),
            Column("submitted_at", String),
            Column("completed_at", String),
            Column("updated_at", String, nullable=False),
        )
        self.seller_verifications = Table(
            "seller_verifications",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("submitted_by", String, nullable=False),
            Column("documents", JSON, nullable=False),
            Column("status", String, nullable=False),
            Column("reviewer_user_id", String),
            Column("decision_note", String),
            Column("decided_at", String),
            Column("created_at", String, nullable=False),
        )
        self.agents = Table(
            "agents",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("name", String, nullable=False),
            Column("status", String, nullable=False),
            Column("policy_ref", String, nullable=False),
            Column("policy_version", String, nullable=False),
            Column("policy_hash", String, nullable=False),
            Column("card_hash", String),
            Column("policy_drift", String, nullable=False, default="0"),
            Column("created_by", String),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
            Column("activated_at", String),
            Column("revoked_at", String),
        )
        self.agent_credentials = Table(
            "agent_credentials",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("agent_id", String, nullable=False, index=True),
            Column("token_hash", String, nullable=False, unique=True),
            Column("scopes", JSON, nullable=False),
            Column("status", String, nullable=False),
            Column("expires_at", String),
            Column("created_at", String, nullable=False),
        )
        self.agent_test_runs = Table(
            "agent_test_runs",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("agent_id", String, nullable=False, index=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("policy_hash", String, nullable=False),
            Column("card_hash", String, nullable=False),
            Column("checks", JSON, nullable=False),
            Column("passed", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.payment_accounts = Table(
            "payment_accounts",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("provider", String, nullable=False),
            Column("provider_account_id", String, nullable=False),
            Column("account_type", String, nullable=False),
            Column("status", String, nullable=False),
            Column("credentials_reference", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.payout_releases = Table(
            "payout_releases",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("approved_by", String, nullable=False),
            Column("reason", String, nullable=False),
            Column("created_at", String, nullable=False),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def upsert_user(
        self, clerk_user_id: str, email: str | None, name: str | None
    ) -> dict:
        existing = await self.get_user_by_clerk_id(clerk_user_id)
        if existing:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.users.update()
                    .where(self.users.c.clerk_user_id == clerk_user_id)
                    .values(
                        email=email if email is not None else existing.get("email"),
                        name=name if name is not None else existing.get("name"),
                        updated_at=_now(),
                    )
                )
            return await self.get_user_by_clerk_id(clerk_user_id)  # ty: ignore[invalid-return-type]
        row = {
            "id": _id(),
            "clerk_user_id": clerk_user_id,
            "email": email,
            "name": name,
            "status": "active",
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.users.insert().values(**row))
        return row

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.users).where(self.users.c.clerk_user_id == clerk_user_id)
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def anonymize_user(self, clerk_user_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.users.update()
                .where(self.users.c.clerk_user_id == clerk_user_id)
                .values(email=None, name=None, status="disabled", updated_at=_now())
            )

    async def upsert_organization(
        self, clerk_org_id: str, name: str, slug: str | None
    ) -> dict:
        existing = await self.get_organization_by_clerk_id(clerk_org_id)
        if existing:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.organizations.update()
                    .where(self.organizations.c.clerk_org_id == clerk_org_id)
                    .values(
                        name=name or existing["name"],
                        slug=slug if slug is not None else existing.get("slug"),
                        updated_at=_now(),
                    )
                )
            return await self.get_organization_by_clerk_id(clerk_org_id)  # ty: ignore[invalid-return-type]
        row = {
            "id": _id(),
            "clerk_org_id": clerk_org_id,
            "kind": "business",
            "name": name,
            "slug": slug,
            "status": "active",
            "owner_user_id": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.organizations.insert().values(**row))
        return row

    async def get_organization(self, org_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.organizations).where(self.organizations.c.id == org_id)
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def get_organization_by_clerk_id(self, clerk_org_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.organizations).where(
                    self.organizations.c.clerk_org_id == clerk_org_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def update_organization(
        self, clerk_org_id: str, name: str | None, slug: str | None
    ) -> None:
        values: dict = {"updated_at": _now()}
        if name is not None:
            values["name"] = name
        if slug is not None:
            values["slug"] = slug
        async with self.engine.begin() as conn:
            await conn.execute(
                self.organizations.update()
                .where(self.organizations.c.clerk_org_id == clerk_org_id)
                .values(**values)
            )

    async def set_organization_status_by_clerk_id(
        self, clerk_org_id: str, status: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.organizations.update()
                .where(self.organizations.c.clerk_org_id == clerk_org_id)
                .values(status=status, updated_at=_now())
            )

    async def upsert_membership(
        self,
        organization_id: str,
        user_id: str,
        role: str,
        clerk_membership_id: str | None = None,
    ) -> dict:
        existing = await self.get_membership(organization_id, user_id)
        if existing:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.organization_members.update()
                    .where(self.organization_members.c.id == existing["id"])
                    .values(
                        role=role,
                        status="active",
                        clerk_membership_id=clerk_membership_id,
                        updated_at=_now(),
                    )
                )
            return await self.get_membership(organization_id, user_id)  # ty: ignore[invalid-return-type]
        row = {
            "id": _id(),
            "organization_id": organization_id,
            "user_id": user_id,
            "role": role,
            "status": "active",
            "clerk_membership_id": clerk_membership_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.organization_members.insert().values(**row))
        return row

    async def get_membership(self, organization_id: str, user_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.organization_members).where(
                    self.organization_members.c.organization_id == organization_id,
                    self.organization_members.c.user_id == user_id,
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def set_membership_status(
        self, organization_id: str, user_id: str, status: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.organization_members.update()
                .where(
                    self.organization_members.c.organization_id == organization_id,
                    self.organization_members.c.user_id == user_id,
                )
                .values(status=status, updated_at=_now())
            )

    async def upsert_membership_from_clerk(self, data: dict) -> dict | None:
        org = data.get("organization") or {}
        pub = data.get("public_user_data") or {}
        clerk_org_id = org.get("id")
        clerk_user_id = pub.get("user_id") or data.get("user_id")
        if not clerk_org_id or not clerk_user_id:
            return None
        local_org = await self.get_organization_by_clerk_id(clerk_org_id)
        local_user = await self.get_user_by_clerk_id(clerk_user_id)
        if local_org is None or local_user is None:
            return None
        role = data.get("role") or "org:member"
        clerk_mem_id = data.get("id")
        return await self.upsert_membership(
            local_org["id"], local_user["id"], role, clerk_mem_id
        )

    async def remove_membership_from_clerk(self, data: dict) -> None:
        org = data.get("organization") or {}
        pub = data.get("public_user_data") or {}
        clerk_org_id = org.get("id")
        clerk_user_id = pub.get("user_id")
        if clerk_org_id and clerk_user_id:
            local_org = await self.get_organization_by_clerk_id(clerk_org_id)
            local_user = await self.get_user_by_clerk_id(clerk_user_id)
            if local_org and local_user:
                await self.set_membership_status(
                    local_org["id"], local_user["id"], "removed"
                )
                return
        clerk_mem_id = data.get("id")
        if clerk_mem_id:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.organization_members.update()
                    .where(
                        self.organization_members.c.clerk_membership_id
                        == clerk_mem_id
                    )
                    .values(status="removed", updated_at=_now())
                )

    async def create_personal_organization(self, user_id: str) -> dict:
        user = None
        async with self.engine.connect() as conn:
            user_row = (
                await conn.execute(select(self.users).where(self.users.c.id == user_id))
            ).first()
            user = dict(user_row._mapping) if user_row else None
        slug = f"personal-{user_id}" if user_id else None
        row = {
            "id": _id(),
            "clerk_org_id": None,
            "kind": "personal",
            "name": (user or {}).get("name") or "Personal",
            "slug": slug,
            "status": "active",
            "owner_user_id": user_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.organizations.insert().values(**row))
        return row

    async def ensure_personal_organization(self, user_id: str) -> dict:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.organizations).where(
                    self.organizations.c.owner_user_id == user_id,
                    self.organizations.c.kind == "personal",
                )
            )
            row = result.first()
            if row is not None:
                return dict(row._mapping)
        return await self.create_personal_organization(user_id)

    async def add_platform_admin(self, user_id: str, granted_by: str | None = None) -> None:
        stmt = sqlite_insert(self.platform_admins).values(
            user_id=user_id, granted_by=granted_by, created_at=_now()
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def is_platform_admin(self, user_id: str) -> bool:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.platform_admins).where(
                    self.platform_admins.c.user_id == user_id
                )
            )
            return result.first() is not None

    async def unique_seller_id(self, base: str | None) -> str:
        slug = (base or "seller").lower().strip()
        slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
        slug = slug.strip("-") or "seller"
        candidate = slug
        n = 2
        while await self.get_seller_profile(candidate) is not None:
            candidate = f"{slug}-{n}"
            n += 1
        return candidate

    async def upsert_seller_profile(
        self, organization_id: str, seller_id: str, display_name: str
    ) -> dict:
        existing = await self.get_seller_profile(seller_id)
        if existing:
            return existing
        row = {
            "seller_id": seller_id,
            "organization_id": organization_id,
            "display_name": display_name,
            "verification_status": "unverified",
            "verification_note": None,
            "verified_at": None,
            "verified_by": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.seller_profiles.insert().values(**row))
        return row

    async def update_seller_display_name(
        self, seller_id: str, display_name: str
    ) -> dict | None:
        existing = await self.get_seller_profile(seller_id)
        if existing is None:
            return None
        async with self.engine.begin() as conn:
            await conn.execute(
                self.seller_profiles.update()
                .where(self.seller_profiles.c.seller_id == seller_id)
                .values(display_name=display_name, updated_at=_now())
            )
        return await self.get_seller_profile(seller_id)

    async def get_seller_profile(self, seller_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.seller_profiles).where(
                    self.seller_profiles.c.seller_id == seller_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def get_seller_profile_by_organization(
        self, organization_id: str
    ) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.seller_profiles).where(
                    self.seller_profiles.c.organization_id == organization_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def set_verification_status(
        self,
        seller_id: str,
        status: str,
        note: str | None = None,
        reviewer_user_id: str | None = None,
    ) -> dict | None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.seller_profiles.update()
                .where(self.seller_profiles.c.seller_id == seller_id)
                .values(
                    verification_status=status,
                    verification_note=note,
                    verified_by=reviewer_user_id,
                    verified_at=_now() if status == "verified" else None,
                    updated_at=_now(),
                )
            )
        return await self.get_seller_profile(seller_id)

    async def ensure_seed_organization(
        self, seller_id: str, kind: str = "business", verified: bool = False
    ) -> dict:
        existing = await self.get_seller_profile(seller_id)
        if existing:
            org = await self.get_organization(existing["organization_id"])
            return org  # ty: ignore[invalid-return-type]
        org_id = _id()
        org = {
            "id": org_id,
            "clerk_org_id": None,
            "kind": kind,
            "name": seller_id,
            "slug": seller_id,
            "status": "active",
            "owner_user_id": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.organizations.insert().values(**org))
        profile = {
            "seller_id": seller_id,
            "organization_id": org_id,
            "display_name": seller_id,
            "verification_status": "verified" if verified else "unverified",
            "verification_note": None,
            "verified_at": _now() if verified else None,
            "verified_by": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.seller_profiles.insert().values(**profile))
        return org

    async def upsert_buyer_profile(self, organization_id: str, buyer_id: str) -> dict:
        existing = await self.get_buyer_profile(buyer_id)
        if existing:
            return existing
        row = {
            "buyer_id": buyer_id,
            "organization_id": organization_id,
            "created_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.buyer_profiles.insert().values(**row))
        return row

    async def get_buyer_profile(self, buyer_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.buyer_profiles).where(
                    self.buyer_profiles.c.buyer_id == buyer_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def get_buyer_profile_by_organization(
        self, organization_id: str
    ) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.buyer_profiles).where(
                    self.buyer_profiles.c.organization_id == organization_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def ensure_seed_buyer_organization(self, buyer_id: str) -> dict:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.buyer_profiles).where(
                    self.buyer_profiles.c.buyer_id == buyer_id
                )
            )
            row = result.first()
            if row is not None:
                bp = dict(row._mapping)
                org_result = await conn.execute(
                    select(self.organizations).where(
                        self.organizations.c.id == bp["organization_id"]
                    )
                )
                org_row = org_result.first()
                if org_row is not None:
                    return dict(org_row._mapping)
        org_id = _id()
        org = {
            "id": org_id,
            "clerk_org_id": None,
            "kind": "personal",
            "name": buyer_id,
            "slug": buyer_id,
            "status": "active",
            "owner_user_id": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.organizations.insert().values(**org))
            await conn.execute(
                self.buyer_profiles.insert().values(
                    buyer_id=buyer_id, organization_id=org_id, created_at=_now()
                )
            )
        return org

    async def upsert_invitation_from_clerk(self, data: dict) -> dict:
        org = data.get("organization") or {}
        clerk_org_id = org.get("id")
        local_org = (
            await self.get_organization_by_clerk_id(clerk_org_id)
            if clerk_org_id
            else None
        )
        if local_org is None:
            return {}
        clerk_inv_id = data.get("id")
        email = data.get("email_address") or data.get("email") or ""
        role = data.get("role") or "org:member"
        existing = None
        if clerk_inv_id:
            async with self.engine.connect() as conn:
                result = await conn.execute(
                    select(self.organization_invitations).where(
                        self.organization_invitations.c.clerk_invitation_id
                        == clerk_inv_id
                    )
                )
                row = result.first()
                existing = dict(row._mapping) if row else None
        if existing:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.organization_invitations.update()
                    .where(
                        self.organization_invitations.c.id == existing["id"]
                    )
                    .values(
                        email=email,
                        role=role,
                        status=data.get("status") or existing["status"],
                        updated_at=_now(),
                    )
                )
            return existing
        row = {
            "id": _id(),
            "organization_id": local_org["id"],
            "clerk_invitation_id": clerk_inv_id,
            "email": email,
            "role": role,
            "status": data.get("status") or "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(
                self.organization_invitations.insert().values(**row)
            )
        return row

    async def revoke_invitation_from_clerk(self, data: dict) -> None:
        clerk_inv_id = data.get("id")
        if not clerk_inv_id:
            return
        async with self.engine.begin() as conn:
            await conn.execute(
                self.organization_invitations.update()
                .where(
                    self.organization_invitations.c.clerk_invitation_id
                    == clerk_inv_id
                )
                .values(status="revoked", updated_at=_now())
            )

    async def record_audit(
        self,
        *,
        scope,
        action,
        organization_id=None,
        transaction_id=None,
        actor_user_id=None,
        actor_type="user",
        resource_id=None,
        payload=None,
    ):
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO audit_log (audit_id, scope, transaction_id, organization_id,"
                " actor_user_id, actor_type, action, resource_id, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    scope,
                    transaction_id,
                    organization_id,
                    actor_user_id,
                    actor_type,
                    action,
                    resource_id,
                    json.dumps(payload or {}),
                    datetime.now(UTC).isoformat(),
                ),
            )

    async def list_audit(
        self,
        *,
        scope=None,
        organization_id=None,
        resource_id=None,
        actor_type=None,
    ) -> list[dict]:
        async with self.engine.connect() as conn:
            result = await conn.exec_driver_sql(
                "SELECT audit_id, scope, transaction_id, organization_id,"
                " actor_user_id, actor_type, actor, action, resource_id, note, payload, created_at"
                " FROM audit_log ORDER BY created_at"
            )
            rows = result.all()
        out: list[dict] = []
        for row in rows:
            d = dict(zip(result.keys(), row))
            if scope is not None and d.get("scope") != scope:
                continue
            if (
                organization_id is not None
                and d.get("organization_id") != organization_id
            ):
                continue
            if resource_id is not None and d.get("resource_id") != resource_id:
                continue
            if actor_type is not None and d.get("actor_type") != actor_type:
                continue
            out.append(d)
        return out

    async def upsert_onboarding(
        self, organization_id: str, status: str, current_step: str
    ) -> dict:
        existing = await self.get_onboarding(organization_id)
        if existing:
            async with self.engine.begin() as conn:
                await conn.execute(
                    self.seller_onboarding.update()
                    .where(
                        self.seller_onboarding.c.organization_id
                        == organization_id
                    )
                    .values(
                        status=status,
                        current_step=current_step,
                        updated_at=_now(),
                    )
                )
            return await self.get_onboarding(organization_id)  # ty: ignore[invalid-return-type]
        row = {
            "organization_id": organization_id,
            "status": status,
            "current_step": current_step,
            "completed_steps": [],
            "submitted_at": None,
            "completed_at": None,
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.seller_onboarding.insert().values(**row))
        return row

    async def get_onboarding(self, organization_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.seller_onboarding).where(
                    self.seller_onboarding.c.organization_id == organization_id
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def create_verification(
        self,
        organization_id: str,
        submitted_by: str,
        documents: list | dict,
    ) -> dict:
        row = {
            "id": _id(),
            "organization_id": organization_id,
            "submitted_by": submitted_by,
            "documents": documents,
            "status": "pending",
            "reviewer_user_id": None,
            "decision_note": None,
            "decided_at": None,
            "created_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.seller_verifications.insert().values(**row))
        return row

    async def decide_verification_row(
        self,
        organization_id: str,
        status: str,
        reviewer_user_id: str | None,
        note: str | None,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.seller_verifications.update()
                .where(
                    self.seller_verifications.c.organization_id == organization_id,
                    self.seller_verifications.c.status == "pending",
                )
                .values(
                    status=status,
                    reviewer_user_id=reviewer_user_id,
                    decision_note=note,
                    decided_at=_now(),
                )
            )

    async def create_agent(
        self,
        *,
        organization_id: str,
        name: str,
        created_by: str | None,
        policy_ref: str,
        policy_version: str,
        policy_hash: str,
        card_hash: str | None = None,
        agent_id: str | None = None,
    ) -> dict:
        row = {
            "id": agent_id if agent_id else _id(),
            "organization_id": organization_id,
            "name": name,
            "status": "draft",
            "policy_ref": policy_ref,
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "card_hash": card_hash,
            "policy_drift": "0",
            "created_by": created_by,
            "created_at": _now(),
            "updated_at": _now(),
            "activated_at": None,
            "revoked_at": None,
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.agents.insert().values(**row))
        return row

    async def get_agent(self, agent_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.agents).where(self.agents.c.id == agent_id)
                )
            ).first()
            return dict(row._mapping) if row else None

    async def list_agents(self, organization_id: str | None = None) -> list[dict]:
        stmt = select(self.agents)
        if organization_id:
            stmt = stmt.where(self.agents.c.organization_id == organization_id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
            return [dict(r._mapping) for r in rows]

    async def set_agent_status(self, agent_id: str, status: str) -> None:
        values: dict = {"status": status, "updated_at": _now()}
        if status == "active":
            values["activated_at"] = _now()
        if status == "revoked":
            values["revoked_at"] = _now()
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agents.update()
                .where(self.agents.c.id == agent_id)
                .values(**values)
            )

    async def set_policy_hash(
        self, agent_id: str, policy_hash: str, policy_version: str | None = None
    ) -> None:
        values: dict = {"policy_hash": policy_hash, "updated_at": _now()}
        if policy_version is not None:
            values["policy_version"] = policy_version
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agents.update()
                .where(self.agents.c.id == agent_id)
                .values(**values)
            )

    async def set_policy_drift(self, agent_id: str, drift: bool) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agents.update()
                .where(self.agents.c.id == agent_id)
                .values(policy_drift="1" if drift else "0", updated_at=_now())
            )

    async def set_card_hash(self, agent_id: str, card_hash: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agents.update()
                .where(self.agents.c.id == agent_id)
                .values(card_hash=card_hash, updated_at=_now())
            )

    async def create_test_run(
        self,
        agent_id: str,
        organization_id: str,
        *,
        policy_hash: str,
        card_hash: str,
        checks: list,
        passed: bool,
    ) -> dict:
        row = {
            "id": _id(),
            "agent_id": agent_id,
            "organization_id": organization_id,
            "policy_hash": policy_hash,
            "card_hash": card_hash,
            "checks": checks,
            "passed": "1" if passed else "0",
            "created_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.agent_test_runs.insert().values(**row))
        return row

    async def latest_passing_test(
        self, agent_id: str, policy_hash: str, card_hash: str
    ) -> dict | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.agent_test_runs)
                    .where(
                        self.agent_test_runs.c.agent_id == agent_id,
                        self.agent_test_runs.c.policy_hash == policy_hash,
                        self.agent_test_runs.c.card_hash == card_hash,
                        self.agent_test_runs.c.passed == "1",
                    )
                    .order_by(self.agent_test_runs.c.created_at.desc())
                )
            ).all()
            return dict(rows[0]._mapping) if rows else None

    async def latest_test_run(self, agent_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.agent_test_runs)
                    .where(self.agent_test_runs.c.agent_id == agent_id)
                    .order_by(self.agent_test_runs.c.created_at.desc())
                )
            ).all()
            return dict(rows[0]._mapping) if rows else None

    async def create_credential(
        self, organization_id: str, agent_id: str, token_hash: str, scopes: list
    ) -> dict:
        row = {
            "id": _id(),
            "organization_id": organization_id,
            "agent_id": agent_id,
            "token_hash": token_hash,
            "scopes": scopes,
            "status": "active",
            "expires_at": None,
            "created_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.agent_credentials.insert().values(**row))
        return row

    async def get_credential_by_hash(self, token_hash: str) -> dict | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.agent_credentials).where(
                        self.agent_credentials.c.token_hash == token_hash
                    )
                )
            ).first()
            return dict(row._mapping) if row else None

    async def list_credentials(self, agent_id: str) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.agent_credentials).where(
                        self.agent_credentials.c.agent_id == agent_id
                    )
                )
            ).all()
            return [dict(r._mapping) for r in rows]

    async def revoke_credential(self, credential_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agent_credentials.update()
                .where(self.agent_credentials.c.id == credential_id)
                .values(status="revoked")
            )

    async def upsert_payment_account(
        self,
        *,
        organization_id: str,
        provider: str,
        provider_account_id: str,
        account_type: str,
        status: str,
        credentials_reference: str,
    ) -> dict:
        from verifund_control_plane.errors import VerifundError

        profile = await self.get_seller_profile_by_organization(organization_id)
        if profile is None or profile["verification_status"] != "verified":
            raise VerifundError(
                "seller_not_verified",
                "seller is not verified for payout accounts",
                status_code=403,
            )
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.payment_accounts).where(
                        self.payment_accounts.c.organization_id == organization_id,
                        self.payment_accounts.c.provider == provider,
                        self.payment_accounts.c.account_type == account_type,
                        self.payment_accounts.c.provider_account_id
                        == provider_account_id,
                    )
                )
            ).first()
            if row is not None:
                return dict(row._mapping)
        new = {
            "id": _id(),
            "organization_id": organization_id,
            "provider": provider,
            "provider_account_id": provider_account_id,
            "account_type": account_type,
            "status": status,
            "credentials_reference": credentials_reference,
            "created_at": _now(),
            "updated_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.payment_accounts.insert().values(**new))
        return new

    async def get_payout_release(
        self, transaction_id: str, organization_id: str
    ) -> dict | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.payout_releases).where(
                        self.payout_releases.c.transaction_id == transaction_id,
                        self.payout_releases.c.organization_id == organization_id,
                    )
                )
            ).first()
            return dict(row._mapping) if row else None

    async def create_payout_release(
        self, transaction_id: str, organization_id: str, approved_by: str, reason: str
    ) -> dict:
        row = {
            "id": _id(),
            "transaction_id": transaction_id,
            "organization_id": organization_id,
            "approved_by": approved_by,
            "reason": reason,
            "created_at": _now(),
        }
        async with self.engine.begin() as conn:
            await conn.execute(self.payout_releases.insert().values(**row))
        return row


async def resolve_payout_account(store, organization_id: str) -> dict:
    from verifund_control_plane.errors import VerifundError

    async with store.engine.connect() as conn:
        rows = (
            await conn.execute(
                select(store.payment_accounts).where(
                    store.payment_accounts.c.organization_id == organization_id,
                    store.payment_accounts.c.provider == "paypal",
                    store.payment_accounts.c.account_type == "payout",
                    store.payment_accounts.c.status == "active",
                )
            )
        ).all()
        accounts = [dict(r._mapping) for r in rows]
    if len(accounts) != 1:
        raise VerifundError(
            "payout_account_unavailable",
            "payout account unavailable",
            status_code=409,
        )
    return accounts[0]


async def resolve_payout_account_for_seller(store, seller_id: str) -> dict:
    profile = await store.get_seller_profile(seller_id)
    if profile is None:
        from verifund_control_plane.errors import VerifundError

        raise VerifundError(
            "payout_account_unavailable",
            "payout account unavailable",
            status_code=409,
        )
    return await resolve_payout_account(store, profile["organization_id"])
