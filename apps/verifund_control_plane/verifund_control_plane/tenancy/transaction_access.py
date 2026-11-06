from __future__ import annotations

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.permissions import ACTION_PERMISSIONS


async def require_transaction(identity, transaction_id, action, repo):
    txn = await repo.get_transaction(transaction_id)
    if identity.tenant_id not in (
        txn.buyer_organization_id,
        txn.seller_organization_id,
    ):
        raise VerifundError(
            "not_found", "transaction not found", status_code=404
        )
    side = "buyer" if identity.tenant_id == txn.buyer_organization_id else "seller"
    permission = ACTION_PERMISSIONS.get((side, action))
    if permission is None:
        raise VerifundError("forbidden", "action not permitted", status_code=403)
    if permission not in identity.permissions:
        raise VerifundError("forbidden", "permission denied", status_code=403)
    return txn, side
