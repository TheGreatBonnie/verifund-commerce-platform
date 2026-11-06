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


async def verify_credential(store, token) -> dict:
    row = await store.get_credential_by_hash(_hash(token))
    if row is None or row["status"] != "active":
        raise VerifundError(
            "unauthorized", "invalid credential", status_code=401
        )
    agent = await store.get_agent(row["agent_id"])
    if agent is None or agent["status"] != "active":
        raise VerifundError(
            "agent_not_active", "agent is not active", status_code=403
        )
    scopes = row["scopes"]
    if isinstance(scopes, str):
        scopes = json.loads(scopes)
    return {
        "organization_id": row["organization_id"],
        "agent_id": row["agent_id"],
        "scopes": scopes,
        "status": "active",
    }
