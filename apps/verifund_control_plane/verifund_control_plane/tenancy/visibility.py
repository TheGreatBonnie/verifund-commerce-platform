from __future__ import annotations

from verifund_control_plane.errors import VerifundError

VISIBILITY: dict[str, set[str]] = {
    "buyer": {"agreement", "offer", "evidence", "transaction", "dispute"},
    "seller": {
        "agreement",
        "offer",
        "evidence",
        "transaction",
        "dispute",
        "catalog",
        "inventory",
        "payout_account",
        "pricing_policy",
    },
}


def assert_resource_visible(side: str, resource: str) -> None:
    if resource not in VISIBILITY.get(side, set()):
        raise VerifundError(
            "forbidden", "resource not visible", status_code=403
        )


def filter_payout_projection(side, payout):
    if side == "buyer":
        return None
    return payout
