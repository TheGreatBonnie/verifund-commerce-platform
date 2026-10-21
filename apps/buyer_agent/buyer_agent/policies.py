from __future__ import annotations

from typing import Any

from commerce_core.contracts import Mandate, Preferences


def default_demo_mandate() -> Mandate:
    return Mandate(
        run_id="demo-run",
        category="consumer-electronics",
        product_hint="Nimbus NC-700 ANC Headset",
        quantity=12,
        max_total_cents=340000,
        deadline_days=14,
        min_warranty_months=24,
        min_returns_days=30,
        preferences=Preferences(sustainability=True, color="black"),
    )


def normalize_approval(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("__agui_cancelled__"):
        return {
            "approved": False,
            "approved_by": "system",
            "note": "Approval cancelled",
        }
    if isinstance(value, dict) and value.get("status") == "resolved":
        value = value.get("payload", {})
    if not isinstance(value, dict):
        raise ValueError("approval response must be an object")
    approved = value.get("approved")
    if isinstance(approved, str):
        approved = approved.lower() in {"true", "yes", "approved", "1"}
    if not isinstance(approved, bool):
        raise ValueError("approval response must include a boolean approved")
    approved_by = str(value.get("approved_by") or "").strip()
    if approved and not approved_by:
        raise ValueError("approved response requires approved_by")
    return {
        "approved": approved,
        "approved_by": approved_by or "system",
        "note": str(value.get("note") or ""),
    }
