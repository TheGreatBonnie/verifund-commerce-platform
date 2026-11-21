from __future__ import annotations

from verifund_control_plane.errors import VerifundError


def authorize_platform_transaction(txn, platform_email: str):
    """Fail closed when a transaction was settled by a different platform account."""
    if not platform_email or getattr(txn, "platform_account_email", None) != platform_email:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return txn
