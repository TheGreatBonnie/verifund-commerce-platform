from __future__ import annotations

import hashlib

from sqlalchemy import select

SEED_SELLERS = {"northwind-audio", "circuitforge", "aurora-supply", "summit-tech"}
BUYER_AGENT_ID = "agent_marketmesh_buyer"
BUYER_ID = "marketmesh-buyer"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _ensure_agent(
    store,
    *,
    organization_id: str,
    agent_id: str,
    name: str,
    policy_ref: str,
) -> dict:
    agent = await store.get_agent(agent_id)
    if agent is None:
        agent = await store.create_agent(
            organization_id=organization_id,
            name=name,
            created_by="seed",
            policy_ref=policy_ref,
            policy_version="1",
            policy_hash="0" * 64,
            agent_id=agent_id,
        )
    if agent["status"] != "active":
        await store.set_agent_status(agent_id, "active")
        agent = await store.get_agent(agent_id)
    return agent


async def _ensure_credential(store, *, organization_id: str, agent_id: str,
                            token: str, scopes: list[str]) -> None:
    if not token:
        return
    digest = _token_hash(token)
    existing = await store.get_credential_by_hash(digest)
    if existing is not None:
        return
    await store.create_credential(
        organization_id, agent_id, digest, scopes)


async def seed_demo_agents(store, settings) -> None:
    """Seed deterministic demo agents for local development.

    This runs only during empty-database bootstrap. It creates the buyer
    agent used by the demo buyer, and — when ``MARKETMESH_SEED_DEMO=1`` —
    one active seller agent per legacy demo seller.

    No static tokens are seeded here: seller and buyer A2A credentials are
    minted on demand via ``issue_credential`` / the internal exchange
    endpoints. A fresh ``vf_agent_*`` is stored hash-only for each agent.
    """
    import os as _os

    from verifund_control_plane.agents.credentials import issue_credential

    buyer_org = await store.ensure_seed_buyer_organization(BUYER_ID)
    await _ensure_agent(
        store,
        organization_id=buyer_org["id"],
        agent_id=BUYER_AGENT_ID,
        name="MarketMesh Buyer",
        policy_ref="marketmesh-buyer/v1",
    )
    # Buyer credential is issued on demand via /v1/internal/buyer-token;
    # seed one active credential so verification passes before first exchange.
    creds = [c for c in await store.list_credentials(BUYER_AGENT_ID) if c["status"] == "active"]
    if not creds:
        await issue_credential(store, buyer_org["id"], BUYER_AGENT_ID, ["a2a:call"])

    if _os.environ.get("MARKETMESH_SEED_DEMO") != "1":
        return
    for seller_id in SEED_SELLERS:
        org = await store.ensure_seed_organization(
            seller_id=seller_id, kind="business", verified=True)
        agent_id = f"agent_{seller_id}"
        await _ensure_agent(
            store,
            organization_id=org["id"],
            agent_id=agent_id,
            name=seller_id,
            policy_ref=f"{seller_id}/v1",
        )
        creds = [c for c in await store.list_credentials(agent_id) if c["status"] == "active"]
        if not creds:
            await issue_credential(store, org["id"], agent_id, ["a2a:test"])


async def _ensure_columns(conn) -> None:
    cols = {
        row[1] for row in await conn.exec_driver_sql("PRAGMA table_info(transactions)")
    }
    if "buyer_organization_id" not in cols:
        await conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN buyer_organization_id TEXT"
        )
    if "seller_organization_id" not in cols:
        await conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN seller_organization_id TEXT"
        )


async def seed_payment_accounts(store, settings) -> None:
    for seller_id, email in (getattr(settings, "seller_payout_emails", {}) or {}).items():
        profile = await store.get_seller_profile(seller_id)
        if profile is None:
            await store.ensure_seed_organization(
                seller_id=seller_id, kind="business", verified=True
            )
            profile = await store.get_seller_profile(seller_id)
            if profile is None:
                continue
        try:
            await store.upsert_payment_account(
                organization_id=profile["organization_id"],
                provider="paypal",
                provider_account_id=email,
                account_type="payout",
                status="active",
                credentials_reference=f"secret:{seller_id}",
            )
        except Exception:  # noqa: BLE001,S112 - per-record tolerance is deliberate
            continue


async def backfill_tenancy(repo, store) -> None:
    async with repo.transaction() as conn:
        await _ensure_columns(conn)
        rows = (await conn.execute(select(repo.transactions))).all()
        for row in rows:
            seller_org = await store.ensure_seed_organization(
                seller_id=row.seller_id,
                kind="business",
                verified=row.seller_id in SEED_SELLERS,
            )
            buyer_org = await store.ensure_seed_buyer_organization(row.buyer_id)
            await conn.execute(
                repo.transactions.update()
                .where(repo.transactions.c.transaction_id == row.transaction_id)
                .values(
                    seller_organization_id=seller_org["id"],
                    buyer_organization_id=buyer_org["id"],
                )
            )
