from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select, true

from verifund_control_plane.errors import VerifundError


@dataclass(frozen=True)
class TenantScope:
    organization_id: str
    user_id: str
    permissions: frozenset[str]
    is_platform_admin: bool = False


class TenantRepository:
    def __init__(self, repo) -> None:
        self.repo = repo

    def _predicate(self, scope: TenantScope, include_all: bool = False):
        t = self.repo.transactions
        if include_all and scope.is_platform_admin:
            return true()
        return or_(
            t.c.buyer_organization_id == scope.organization_id,
            t.c.seller_organization_id == scope.organization_id,
        )

    async def get_transaction(self, scope, transaction_id):
        async with self.repo.transaction() as conn:
            row = (
                await conn.execute(
                    select(self.repo.transactions).where(
                        self.repo.transactions.c.transaction_id == transaction_id,
                        self._predicate(scope),
                    )
                )
            ).first()
        if row is None:
            raise VerifundError(
                "not_found", "transaction not found", status_code=404
            )
        return self.repo._record(row)

    async def list_transactions(
        self,
        scope,
        state: str | None = None,
        limit: int = 50,
        include_all_tenants: bool = False,
    ):
        statement = (
            select(self.repo.transactions)
            .where(self._predicate(scope, include_all_tenants))
            .order_by(self.repo.transactions.c.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        if state:
            statement = statement.where(self.repo.transactions.c.state == state)
        async with self.repo.transaction() as conn:
            rows = (await conn.execute(statement)).all()
        return [self.repo._record(row) for row in rows]
