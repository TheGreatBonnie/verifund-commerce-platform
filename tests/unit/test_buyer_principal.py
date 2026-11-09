from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.api.buyer_auth import (
    BuyerPrincipal,
    authorize_buyer_transaction,
    buyer_owns_transaction,
    resolve_buyer_principal,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


class Req(Request):
    def __init__(self, headers=None, app=None):
        raw_headers = [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in (headers or {}).items()
        ]
        super().__init__(
            {"type": "http", "method": "GET", "headers": raw_headers, "app": app}
        )


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
async def seeded_buyer(tenancy):
    ten, core = tenancy
    org = await ten.upsert_organization("org_b1", "Buyer Org", "buyer-org")
    await ten.upsert_buyer_profile(org["id"], "demo-buyer", clerk_user_id="user_buyer")
    return ten, core, org


async def test_internal_auth_resolves_principal(seeded_buyer):
    ten, _core, org = seeded_buyer
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(buyer_settlement_internal_token="buyer-secret"),
        )
    )
    request = Req(
        headers={
            "x-verifund-buyer-internal-token": "buyer-secret",
            "x-buyer-clerk-user-id": "user_buyer",
        },
        app=app,
    )
    principal = await resolve_buyer_principal(request, required_scope="txn:read")
    assert principal == BuyerPrincipal(
        buyer_id="demo-buyer",
        clerk_user_id="user_buyer",
        actor="service:buyer-settlement",
        auth_kind="internal_service",
        scopes=frozenset({"txn:read", "txn:act", "agreement:decide"}),
    )


async def test_internal_auth_wrong_token_is_401(seeded_buyer):
    ten, _core, org = seeded_buyer
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(buyer_settlement_internal_token="buyer-secret"),
        )
    )
    request = Req(
        headers={"x-verifund-buyer-internal-token": "bad", "x-buyer-clerk-user-id": "user_buyer"},
        app=app,
    )
    with pytest.raises(VerifundError) as exc:
        await resolve_buyer_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 401


async def test_internal_auth_missing_context_is_401(seeded_buyer):
    ten, _core, _org = seeded_buyer
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(buyer_settlement_internal_token="buyer-secret"),
        )
    )
    request = Req(headers={"x-verifund-buyer-internal-token": "buyer-secret"}, app=app)
    with pytest.raises(VerifundError) as exc:
        await resolve_buyer_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 401


async def test_internal_auth_mismatched_buyer_id_is_403(seeded_buyer):
    ten, _core, org = seeded_buyer
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(buyer_settlement_internal_token="buyer-secret"),
        )
    )
    request = Req(
        headers={
            "x-verifund-buyer-internal-token": "buyer-secret",
            "x-buyer-clerk-user-id": "user_buyer",
            "x-buyer-id": "other-buyer",
        },
        app=app,
    )
    with pytest.raises(VerifundError) as exc:
        await resolve_buyer_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 403


async def test_clerk_auth_resolves_principal(seeded_buyer):
    ten, _core, org = seeded_buyer
    user = await ten.upsert_user("user_buyer", "buyer@example.com", "Buyer")
    await ten.upsert_membership(org["id"], user["id"], "org:buyer", "mem_buyer")
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(buyer_settlement_internal_token=None),
            clerk_authenticator=lambda request: {
                "sub": "user_buyer",
                "org_id": org["clerk_org_id"],
                "org_role": "org:buyer",
            },
        )
    )
    request = Req(headers={"authorization": "Bearer t"}, app=app)
    principal = await resolve_buyer_principal(request, required_scope="txn:read")
    assert principal.auth_kind == "clerk"
    assert principal.buyer_id == "demo-buyer"
    assert principal.clerk_user_id == "user_buyer"
    assert principal.actor == f"user:{user['id']}"
    assert "txn:read" in principal.scopes


async def test_buyer_owns_transaction_by_id():
    principal = BuyerPrincipal(
        buyer_id="demo-buyer",
        clerk_user_id="user_buyer",
        actor="user:u1",
        auth_kind="clerk",
        scopes=frozenset({"txn:read"}),
    )
    assert buyer_owns_transaction(principal, SimpleNamespace(buyer_id="demo-buyer"))
    assert not buyer_owns_transaction(principal, SimpleNamespace(buyer_id="other"))


async def test_authorize_buyer_transaction_404s_on_cross_tenant(seeded_buyer):
    ten, core, org = seeded_buyer
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            repo=core,
            settings=SimpleNamespace(buyer_settlement_internal_token="buyer-secret"),
        )
    )
    # transaction record owned by other buyer
    record = SimpleNamespace(buyer_id="other-buyer")
    core.get_transaction = lambda tid, conn=None: _arecord(record)
    async def _arecord(r):
        return r
    request = Req(
        headers={"x-verifund-buyer-internal-token": "buyer-secret", "x-buyer-clerk-user-id": "user_buyer"},
        app=app,
    )
    with pytest.raises(VerifundError) as exc:
        await authorize_buyer_transaction(request, "tx-1", required_scope="txn:act")
    assert exc.value.status_code == 404


def test_buyer_settlement_internal_token_setting(monkeypatch):
    from verifund_control_plane.settings import Settings

    monkeypatch.setenv("VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN", "secret-token")
    s = Settings(_env_file=None)
    assert s.buyer_settlement_internal_token == "secret-token"


async def test_authorize_buyer_agreement_claims_unlinked_profile_for_clerk_user(tenancy):
    """A Clerk buyer whose user is not yet linked can adopt an
    unlinked (agent-seeded) buyer profile on first decision, mirroring
    the live HITL flow where the agreement buyer_id is the agent's
    synthetic id (``buyer_agent``) and the human approver is a real
    Clerk user with no link yet."""
    from verifund_control_plane.api.buyer_auth import authorize_buyer_agreement

    ten, _core = tenancy
    org = await ten.upsert_organization("org_agent", "Agent Buyer Org", "agent-buyer")
    await ten.upsert_buyer_profile(org["id"], "buyer_agent")
    await ten.upsert_user("user_human", "human@example.com", "Human")
    # Personal-org style identity: no Clerk org_id, role org:buyer via
    # ensure_personal_organization fallback in resolve_identity.
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                buyer_settlement_internal_token=None,
                clerk_secret_key="",
            ),
            clerk_authenticator=lambda request: {
                "sub": "user_human",
                "email": "human@example.com",
            },
        )
    )
    request = Req(headers={"authorization": "Bearer t"}, app=app)
    agreement = SimpleNamespace(buyer_id="buyer_agent")
    principal = await authorize_buyer_agreement(
        request, agreement, required_scope="agreement:decide"
    )
    assert principal.buyer_id == "buyer_agent"
    assert principal.clerk_user_id == "user_human"
    profile = await ten.get_buyer_profile("buyer_agent")
    assert profile["clerk_user_id"] == "user_human"


async def test_authorize_buyer_agreement_allows_second_unlinked_variant_for_linked_user(tenancy):
    """Buyer-agent mandates use varying synthetic buyer ids
    (``buyer_agent``, ``BUYER-AGENT-001``, ...). A Clerk user already
    linked to one variant must still be able to approve an agreement
    whose buyer profile is a different, unlinked variant (live
    ``agr_60cd65b0...`` -> 404)."""
    from verifund_control_plane.api.buyer_auth import authorize_buyer_agreement

    ten, _core = tenancy
    org1 = await ten.upsert_organization("org_a1", "Buyer Org 1", "buyer-1")
    await ten.upsert_buyer_profile(
        org1["id"], "buyer_agent", clerk_user_id="user_human"
    )
    org2 = await ten.upsert_organization("org_a2", "Buyer Org 2", "buyer-2")
    await ten.upsert_buyer_profile(org2["id"], "BUYER-AGENT-001")
    await ten.upsert_user("user_human", "human@example.com", "Human")
    app = SimpleNamespace(
        state=SimpleNamespace(
            tenancy=ten,
            settings=SimpleNamespace(
                buyer_settlement_internal_token=None,
                clerk_secret_key="",
            ),
            clerk_authenticator=lambda request: {
                "sub": "user_human",
                "email": "human@example.com",
            },
        )
    )
    request = Req(headers={"authorization": "Bearer t"}, app=app)
    agreement = SimpleNamespace(buyer_id="BUYER-AGENT-001")
    principal = await authorize_buyer_agreement(
        request, agreement, required_scope="agreement:decide"
    )
    assert principal.buyer_id == "BUYER-AGENT-001"
    assert principal.clerk_user_id == "user_human"
