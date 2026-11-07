from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.api.seller_auth import (
    SellerPrincipal,
    authorize_seller_transaction,
    resolve_seller_principal,
    seller_owns_transaction,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


class Req:
    def __init__(self, headers=None, app=None):
        self.headers = headers or {}
        self.app = app


@pytest.fixture
async def tenancy(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    ten = TenancyRepository(engine)
    core = Repository(engine)
    async with engine.begin() as conn:
        await conn.run_sync(core.metadata.create_all)
        await conn.run_sync(ten.metadata.create_all)
    yield ten, core
    await engine.dispose()


@pytest.fixture
async def seeded_seller(tenancy):
    ten, core = tenancy
    org = await ten.upsert_organization("org_s1", "Seller Org", "seller-org")
    await ten.upsert_seller_profile(org["id"], "northwind", "Northwind")
    return ten, core, org


async def test_internal_auth_resolves_principal(seeded_seller):
    ten, _core, org = seeded_seller
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token="secret", seller_internal_token=None
            ),
        )
    )
    request = Req(
        headers={
            "x-verifund-internal-token": "secret",
            "x-seller-org-id": org["id"],
        },
        app=app,
    )
    principal = await resolve_seller_principal(request, required_scope="txn:read")
    assert principal == SellerPrincipal(
        seller_id="northwind",
        organization_id=org["id"],
        actor="service:settlement",
        auth_kind="internal_service",
        scopes=frozenset({"txn:read", "evidence:write"}),
    )


async def test_internal_auth_wrong_token_is_401(seeded_seller):
    ten, _core, org = seeded_seller
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token="secret", seller_internal_token=None
            ),
        )
    )
    request = Req(
        headers={"x-verifund-internal-token": "bad", "x-seller-org-id": org["id"]},
        app=app,
    )
    with pytest.raises(VerifundError) as exc:
        await resolve_seller_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 401


async def test_internal_auth_missing_context_is_401(seeded_seller):
    ten, _core, _org = seeded_seller
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token="secret", seller_internal_token=None
            ),
        )
    )
    request = Req(headers={"x-verifund-internal-token": "secret"}, app=app)
    with pytest.raises(VerifundError) as exc:
        await resolve_seller_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 401


async def test_internal_auth_mismatched_seller_id_is_403(seeded_seller):
    ten, _core, org = seeded_seller
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token="secret", seller_internal_token=None
            ),
        )
    )
    request = Req(
        headers={
            "x-verifund-internal-token": "secret",
            "x-seller-org-id": org["id"],
            "x-seller-id": "other-seller",
        },
        app=app,
    )
    with pytest.raises(VerifundError) as exc:
        await resolve_seller_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 403


async def test_internal_auth_resolves_from_seller_id(seeded_seller):
    ten, _core, org = seeded_seller
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token="secret", seller_internal_token=None
            ),
        )
    )
    request = Req(
        headers={
            "x-verifund-internal-token": "secret",
            "x-seller-id": "northwind",
        },
        app=app,
    )
    principal = await resolve_seller_principal(request, required_scope="evidence:write")
    assert principal.seller_id == "northwind"
    assert principal.organization_id == org["id"]
    assert "evidence:write" in principal.scopes


async def test_clerk_auth_resolves_principal(seeded_seller):
    ten, _core, org = seeded_seller
    user = await ten.upsert_user("user_seller", "seller@example.com", "Seller")
    await ten.upsert_membership(org["id"], user["id"], "org:admin", "mem_seller")
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                settlement_internal_token=None, seller_internal_token=None
            ),
            clerk_authenticator=lambda request: {
                "sub": "user_seller",
                "org_id": org["clerk_org_id"],
                "org_role": "org:admin",
            },
        )
    )
    request = Req(headers={"authorization": "Bearer t"}, app=app)
    principal = await resolve_seller_principal(request, required_scope="txn:read")
    assert principal.auth_kind == "clerk"
    assert principal.seller_id == "northwind"
    assert principal.organization_id == org["id"]
    assert principal.actor == f"user:{user['id']}"
    assert "txn:read" in principal.scopes
