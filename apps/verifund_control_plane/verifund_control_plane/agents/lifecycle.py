from __future__ import annotations

from verifund_control_plane.errors import VerifundError

ALLOWED = {
    "draft": {"configuring", "revoked"},
    "configuring": {"testing", "revoked"},
    "testing": {"active", "configuring"},
    "active": {"suspended", "revoked"},
    "suspended": {"active", "revoked"},
    "revoked": set(),
}


async def _transition(store, agent_id: str, target: str) -> dict:
    agent = await store.get_agent(agent_id)
    if agent is None:
        raise VerifundError("not_found", "agent not found", status_code=404)
    if target not in ALLOWED.get(agent["status"], set()):
        raise VerifundError(
            "invalid_state", "invalid agent transition", status_code=409
        )
    await store.set_agent_status(agent_id, target)
    return await store.get_agent(agent_id)


async def provision_agent(
    store, organization_id, name, created_by, policy_ref, idempotency_key=None
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None or profile["verification_status"] not in ("pending", "verified"):
        raise VerifundError(
            "seller_not_verified",
            "seller is not verified for agent provisioning",
            status_code=403,
        )
    existing = [a for a in await store.list_agents(organization_id) if a["name"] == name and a["status"] != "revoked"]
    if existing and idempotency_key:
        return existing[0]
    agent = await store.create_agent(
        organization_id=organization_id,
        name=name,
        created_by=created_by,
        policy_ref=policy_ref,
        policy_version="1",
        policy_hash="0" * 64,
    )
    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=created_by,
        actor_type="user",
        action="agent.provisioned",
        resource_id=agent["id"],
        payload={"name": name},
    )
    return agent


async def confirm_policy(store, agent_id, version, hash) -> dict:
    agent = await store.get_agent(agent_id)
    if agent is None:
        raise VerifundError("not_found", "agent not found", status_code=404)
    drift = agent["policy_hash"] != hash
    await store.set_policy_hash(agent_id, hash, policy_version=version)
    await store.set_policy_drift(agent_id, False if not drift else True)
    # confirm clears drift: the confirmed hash is the new baseline
    await store.set_policy_drift(agent_id, False)
    updated = await store.get_agent(agent_id)
    await store.record_audit(
        scope="organization",
        organization_id=updated["organization_id"],
        actor_user_id=updated.get("created_by"),
        actor_type="user",
        action="agent.policy_confirmed",
        resource_id=agent_id,
        payload={"policy_version": version},
    )
    return updated


async def check_drift(store, agent) -> bool:
    return (agent.get("policy_drift") or "0") == "1"


async def activate_agent(store, agent_id, actor_agent_id=None) -> dict:
    agent = await store.get_agent(agent_id)
    if agent is None:
        raise VerifundError("not_found", "agent not found", status_code=404)
    if agent.get("policy_drift") == "1":
        raise VerifundError("policy_drift", "policy drift detected", status_code=409)
    profile = await store.get_seller_profile_by_organization(agent["organization_id"])
    if profile is None or profile["verification_status"] != "verified":
        raise VerifundError(
            "seller_not_verified", "seller is not verified", status_code=403
        )
    card_hash = agent.get("card_hash") or ""
    passing = await store.latest_passing_test(
        agent_id, agent["policy_hash"], card_hash
    )
    if passing is None:
        raise VerifundError(
            "onboarding_incomplete", "no passing test run", status_code=409
        )
    creds = [c for c in await store.list_credentials(agent_id) if c["status"] == "active"]
    if not creds:
        raise VerifundError(
            "onboarding_incomplete", "no active credential", status_code=409
        )
    updated = await _transition(store, agent_id, "active")
    await store.record_audit(
        scope="organization",
        organization_id=agent["organization_id"],
        actor_user_id=actor_agent_id,
        actor_type="agent" if actor_agent_id else "user",
        action="agent.activated",
        resource_id=agent_id,
        payload={},
    )
    return updated
