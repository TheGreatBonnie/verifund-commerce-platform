from __future__ import annotations

from sqlalchemy import select

SEED_SELLERS = {"northwind-audio", "circuitforge", "aurora-supply", "summit-tech"}


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
            org = await store.ensure_seed_organization(
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
        except Exception:
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
