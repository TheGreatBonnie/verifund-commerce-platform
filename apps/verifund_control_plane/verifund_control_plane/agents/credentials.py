from __future__ import annotations

import hashlib
import json
import secrets

from verifund_control_plane.errors import VerifundError


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_credential(store, organization_id, agent_id, scopes) -> str:
    token = "vf_agent_" + secrets.token_urlsafe(32)
    await store.create_credential(organization_id, agent_id, _hash(token), scopes)
    return token


async def revoke_credential_by_raw(store, organization_id, raw_token: str) -> bool:
    row = await store.get_credential_by_hash(_hash(raw_token))
    if row is None or row["organization_id"] != organization_id:
        return False
    await store.revoke_credential(row["id"])
    return True


async def verify_credential(store, token, *, purpose: str = "a2a:call") -> dict:
    row = await store.get_credential_by_hash(_hash(token))
    if row is None or row["status"] != "active":
        raise VerifundError(
            "unauthorized", "invalid credential", status_code=401
        )
    agent = await store.get_agent(row["agent_id"])
    if agent is None:
        raise VerifundError(
            "agent_not_found", "agent not found", status_code=403
        )
    scopes = row["scopes"]
    if isinstance(scopes, str):
        scopes = json.loads(scopes)
    if purpose == "a2a:test":
        # Pre-activation test verification (B.4.3). Accepts an `a2a:test`-scoped
        # credential against a non-revoked agent that is being tested, but never
        # authorizes A2A traffic for non-active agents: callers must use the
        # default purpose, which requires agent status == "active".
        if "a2a:test" not in scopes:
            raise VerifundError(
                "scope_insufficient",
                "a2a:test scope required for test verification",
                status_code=403,
            )
        if agent["status"] not in ("configuring", "testing", "active"):
            raise VerifundError(
                "agent_not_active", "agent is not active", status_code=403
            )
    elif agent["status"] != "active":
        raise VerifundError(
            "agent_not_active", "agent is not active", status_code=403
        )
    return {
        "organization_id": row["organization_id"],
        "agent_id": row["agent_id"],
        "scopes": scopes,
        "status": "active",
    }
