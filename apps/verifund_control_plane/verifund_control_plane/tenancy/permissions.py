from __future__ import annotations

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "org:admin": frozenset(
        {
            "org:transactions:read",
            "org:transactions:approve",
            "org:evidence:read",
            "org:evidence:write",
            "org:payouts:read",
            "org:payouts:manage",
            "org:mandates:manage",
            "org:disputes:resolve",
            "org:agents:manage",
            "org:members:manage",
        }
    ),
    "org:member": frozenset(
        {"org:transactions:read", "org:evidence:read"}
    ),
    "org:sales": frozenset(
        {
            "org:transactions:read",
            "org:evidence:read",
            "org:mandates:manage",
        }
    ),
    "org:fulfillment": frozenset(
        {
            "org:transactions:read",
            "org:evidence:read",
            "org:evidence:write",
        }
    ),
    "org:finance": frozenset(
        {
            "org:transactions:read",
            "org:payouts:read",
            "org:payouts:manage",
        }
    ),
    "org:reviewer": frozenset(
        {
            "org:transactions:read",
            "org:evidence:read",
            "org:disputes:resolve",
        }
    ),
    "org:agent_manager": frozenset(
        {"org:mandates:manage", "org:agents:manage"}
    ),
    "org:buyer": frozenset(
        {
            "org:transactions:read",
            "org:transactions:approve",
            "org:evidence:read",
        }
    ),
}

ACTION_PERMISSIONS: dict[tuple[str, str], str] = {
    ("buyer", "read"): "org:transactions:read",
    ("seller", "read"): "org:transactions:read",
    ("buyer", "approve_agreement"): "org:transactions:approve",
    ("seller", "approve_agreement"): "org:transactions:approve",
    ("seller", "upload_evidence"): "org:evidence:write",
    ("buyer", "upload_evidence"): "org:evidence:write",
    ("seller", "release_funds"): "org:transactions:approve",
    ("buyer", "release_funds"): "org:transactions:approve",
    ("seller", "manage_payouts"): "org:payouts:manage",
    ("seller", "read_payouts"): "org:payouts:read",
    ("seller", "manage_mandates"): "org:mandates:manage",
    ("seller", "manage_agents"): "org:agents:manage",
    ("buyer", "resolve_dispute"): "org:disputes:resolve",
    ("seller", "resolve_dispute"): "org:disputes:resolve",
    ("seller", "manage_members"): "org:members:manage",
}
