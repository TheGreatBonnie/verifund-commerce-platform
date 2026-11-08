from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from verifund_control_plane.agents.cards import build_seller_card
from verifund_control_plane.agents.credentials import (
    issue_credential,
    revoke_credential_by_raw,
    verify_credential,
)
from verifund_control_plane.agents.lifecycle import activate_agent, confirm_policy
from verifund_control_plane.agents.registry_sync import publish_seller
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import advance_step, require_step
from verifund_control_plane.tenancy.identity import require_identity

router = APIRouter()


class VerifyRequest(BaseModel):
    token: str = Field(min_length=1)
    purpose: str = Field(default="a2a:call", pattern="^(a2a:call|a2a:test)$")


class IssueRequest(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["a2a:call"])


class CreateAgentBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)


class ConfigBody(BaseModel):
    expected_config_version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=128)
    tagline: str | None = Field(default=None, max_length=256)
    instructions: str | None = Field(default=None, max_length=4096)
    tool_allowlist: list[str] | None = None
    max_discount_bps: int | None = Field(default=None, ge=0, le=10_000)
    autonomy_mode: str | None = Field(
        default=None, pattern="^(read_only|assisted|policy_bounded)$")


class CatalogImportBody(BaseModel):
    document: str = Field(min_length=2, max_length=2 * 1024 * 1024)
    replace_catalog: bool = False


def generate_instructions(
    *,
    name: str | None,
    tagline: str | None,
    allowlist: list[str] | None,
    max_discount_bps: int | None,
    autonomy_mode: str | None,
    categories: list[str] | None = None,
) -> str:
    """Deterministic template draft (no LLM call); policy bounds always win."""
    display = (name or "Seller agent").strip() or "Seller agent"
    cats = ", ".join(categories or []) or "your catalog"
    caps = ", ".join(allowlist or []) or "catalog search and quoting"
    discount = "10%" if max_discount_bps is None else f"{(max_discount_bps / 100):.2f}%".rstrip("0").rstrip(".")
    mode = autonomy_mode or "policy_bounded"
    text = (
        f"You are {display}'s seller agent. "
        f"{tagline.strip() + '. ' if tagline and tagline.strip() else ''}"
        f"Present as a trusted seller for {cats}. "
        f"Capabilities: {caps}. "
        "Qualify first: ask quantity, use case, deadline, and budget before quoting. "
        "Never go below your floor; concede in small steps toward the listed ladder. "
        f"Mode: {mode}. Max discount: {discount}. "
        "Offer the warranty extension before increasing discount. "
        "Keep evidence ready for verification."
    )
    return text[:4096]


def _idem_key(request: Request) -> str | None:
    key = (request.headers.get("idempotency-key") or "").strip()
    return key[:128] or None


async def require_seller_agent_admin(request: Request):
    identity = await require_identity(request)
    if "org:agents:manage" not in identity.permissions:
        raise VerifundError(
            "forbidden", "org:agents:manage required", status_code=403)
    store = request.app.state.tenancy
    org = await store.get_organization(identity.tenant_id)
    if org is None or org["kind"] != "business":
        raise VerifundError(
            "forbidden", "seller onboarding requires a business organization",
            status_code=403)
    return identity


async def require_own_agent(request: Request, agent_id: str, identity):
    store = request.app.state.tenancy
    agent = await store.get_agent(agent_id)
    if agent is None or agent["organization_id"] != identity.tenant_id:
        raise VerifundError("not_found", "agent not found", status_code=404)
    return agent


async def _call_runtime(request: Request, path: str, *,
                        headers: dict[str, str],
                        json_body: dict | None = None,
                        method: str = "POST",
                        timeout: float = 20.0) -> httpx.Response:
    settings = request.app.state.settings
    if not getattr(settings, "seller_internal_token", None):
        raise VerifundError(
            "seller_runtime_unavailable",
            "seller runtime not configured",
            status_code=503)
    service_headers = {**headers, "x-internal-token": settings.seller_internal_token}
    runtime = getattr(request.app.state, "runtime_client_factory", None)

    async def _send(client: httpx.AsyncClient) -> httpx.Response:
        if method.upper() == "GET":
            return await client.get(path, headers=service_headers)
        return await client.post(path, headers=service_headers,
                                 json=json_body or {})

    if runtime is not None:
        async with runtime() as client:
            return await _send(client)
    try:
        async with httpx.AsyncClient(base_url=settings.seller_agent_url,
                                     timeout=httpx.Timeout(timeout)) as client:
            return await _send(client)
    except httpx.HTTPError as e:
        raise VerifundError(
            "seller_runtime_unavailable",
            f"seller runtime unreachable: {e}",
            status_code=503)


@router.post("/v1/agents/{agent_id}/test")
async def test_agent(agent_id: str, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    await require_step(store, identity.tenant_id, "catalog")

    credential = await issue_credential(
        store, identity.tenant_id, agent_id, ["a2a:test"])
    revoked = await issue_credential(
        store, identity.tenant_id, agent_id, ["a2a:test"])
    await revoke_credential_by_raw(store, identity.tenant_id, revoked)

    if agent["status"] in ("draft", "configuring"):
        await store.set_agent_status(agent_id, "testing")

    response = await _call_runtime(
        request,
        "/internal/test-suite",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
        json_body={"agent_id": agent_id,
                   "credential": credential,
                   "revoked_credential": revoked},
    )
    if response.status_code >= 400:
        raise VerifundError(
            "runtime_error", response.text, status_code=502)
    result = response.json()
    checks = [c for c in result.get("checks", [])]
    passed = bool(result.get("passed", False))
    run = await store.create_test_run(
        agent_id,
        identity.tenant_id,
        policy_hash=agent.get("policy_hash") or "",
        card_hash=agent.get("card_hash") or "",
        checks=checks,
        passed=passed,
    )
    if not passed:
        await store.set_agent_status(agent_id, "configuring")
    else:
        await advance_step(store, identity.tenant_id, "verification")
    return {"passed": passed, "checks": checks, "run_id": run["id"]}


@router.post("/v1/agent-credentials/verify")
async def verify(request: Request, body: VerifyRequest) -> dict:
    return await verify_credential(request.app.state.tenancy, body.token,
                                   purpose=body.purpose)


@router.post("/v1/agents/{agent_id}/credentials", status_code=201)
async def issue(request: Request, agent_id: str, body: IssueRequest) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    agent = await store.get_agent(agent_id)
    if agent is None or agent["organization_id"] != identity.tenant_id:
        raise VerifundError("not_found", "agent not found", status_code=404)
    raw = await issue_credential(store, identity.tenant_id, agent_id, body.scopes)
    return {"credential": raw}


class InternalTokenBody(BaseModel):
    seller_id: str = Field(min_length=1)


@router.post("/v1/internal/agent-token")
async def internal_agent_token(request: Request, body: InternalTokenBody) -> dict:
    settings = request.app.state.settings
    if request.headers.get("X-Internal-Token") != getattr(settings, "buyer_internal_token", ""):
        raise VerifundError("unauthorized", "invalid internal token", status_code=401)
    store = request.app.state.tenancy
    agent = await store.get_agent(f"agent_{body.seller_id}")
    if agent is None:
        raise VerifundError("not_found", "agent not found", status_code=404)
    if agent["status"] != "active":
        raise VerifundError("agent_not_active", "agent is not active", status_code=403)
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    return {"agent_id": agent["id"], "token": raw, "scopes": ["a2a:call"]}


async def _forward_config(request: Request, agent_id: str, identity,
                          body: ConfigBody, agent: dict):
    # seller_id is anchored to policy_ref ("{seller_id}/vN"); keep it stable.
    seller_id = (agent.get("policy_ref") or f"{agent_id}/v1").split("/")[0]
    json_body: dict[str, Any] = {"agent_id": agent_id,
                                 "organization_id": identity.tenant_id,
                                 "seller_id": seller_id,
                                 "name": body.name,
                                 "tagline": body.tagline,
                                 "instructions": body.instructions,
                                 "tool_allowlist": body.tool_allowlist,
                                 "max_discount_bps": body.max_discount_bps,
                                 "autonomy_mode": body.autonomy_mode,
                                 "expected_config_version": body.expected_config_version}
    # Drop unset fields so the runtime keeps existing config values (PUT semantics).
    json_body = {k: v for k, v in json_body.items() if v is not None}
    return await _call_runtime(
        request, "/internal/agent-configs",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
        json_body=json_body)


@router.post("/v1/agents", status_code=201)
async def create_agent_route(request: Request, response: Response,
                             body: CreateAgentBody | None = None) -> dict:
    if body is None:
        body = CreateAgentBody()
    identity = await require_seller_agent_admin(request)
    store = request.app.state.tenancy
    idempotency_key = _idem_key(request)
    import uuid
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    await require_step(store, identity.tenant_id, "profile")
    seller_id = (profile or {}).get("seller_id") or uuid.uuid4().hex
    agent_id = f"agent_{seller_id}"

    existing = [a for a in await store.list_agents(identity.tenant_id)
                if a["id"] == agent_id]
    if existing:
        response.status_code = 200
        return {"agent_id": agent_id, "status": existing[0]["status"]}
    display = (body.display_name or (profile or {}).get("name") or "Seller agent").strip()

    agent = await store.create_agent(
        organization_id=identity.tenant_id,
        name=display,
        created_by=identity.user_id,
        policy_ref=f"{seller_id}/v1",
        policy_version="1",
        policy_hash="0" * 64,
        agent_id=agent_id,
    )
    runtime_response = await _call_runtime(
        request, "/internal/agent-configs",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent["id"]},
        json_body={"agent_id": agent["id"],
                   "organization_id": identity.tenant_id,
                   "seller_id": seller_id,
                   "name": display,
                   "tagline": (profile or {}).get("tagline") or ""})
    if runtime_response.status_code >= 400:
        raise VerifundError(
            "provisioning_failed", runtime_response.text, status_code=502)
    await store.record_audit(
        scope="agents", organization_id=identity.tenant_id,
        actor_user_id=identity.user_id, actor_type="user",
        action="agent.created", resource_id=agent["id"],
        payload={"idempotency_key": idempotency_key, "agent_id": agent["id"]},
    )
    await advance_step(store, identity.tenant_id, "config")
    return {"agent_id": agent["id"], "status": "draft",
            **runtime_response.json()}


def _seller_id(agent: dict, agent_id: str) -> str:
    return (agent.get("policy_ref") or f"{agent_id}/v1").split("/")[0]


def _card_hash(card: dict) -> str:
    return hashlib.sha256(
        json.dumps(card, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()


async def _record_hashes(request: Request, store, identity, agent_id: str,
                         agent: dict, snapshot: dict) -> None:
    """Persist the runtime-computed policy and card hashes on the CP agent row.

    The control plane records the hashes (§12.4 / B.5 step 6) so the
    activation gate (`latest_passing_test` on current hashes) is meaningful.
    """
    policy_hash = snapshot.get("policy_hash")
    if policy_hash:
        await confirm_policy(
            store, agent_id,
            str(snapshot.get("policy_version") or "1"),
            str(policy_hash),
        )
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    seller_id = _seller_id(agent, agent_id)
    settings = request.app.state.settings
    base_url = getattr(settings, "agents_public_base_url",
                       "https://agents.verifund.com")
    card = build_seller_card(
        profile=profile,
        agent_name=snapshot.get("name") or (profile or {}).get("name")
        or "Seller agent",
        agent_id=agent_id,
        allowlist=snapshot.get("tool_allowlist") or [],
        base_url=base_url,
        seller_id=seller_id,
    )
    await store.set_card_hash(agent_id, _card_hash(card))


@router.post("/v1/agents/{agent_id}/instructions/generate")
async def generate_agent_instructions(agent_id: str, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    snapshot_resp = await _call_runtime(
        request, f"/internal/agent-configs/{agent_id}",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id}, method="GET", timeout=5.0,
    )
    snapshot = snapshot_resp.json() if snapshot_resp.status_code < 400 else {}
    try:
        cats = snapshot.get("categories") or []
        # Runtime returns product categories when configured; fall back to generic
        if not cats:
            cats = sorted({c for c in ((profile or {}).get("categories") or [])})
    except Exception:
        cats = []
    name = snapshot.get("name") or (profile or {}).get("name") or agent.get("name") or "Seller agent"
    text = generate_instructions(
        name=name,
        tagline=snapshot.get("tagline") or ((profile or {}).get("tagline") or ""),
        allowlist=snapshot.get("tool_allowlist") or [],
        max_discount_bps=snapshot.get("max_discount_bps"),
        autonomy_mode=snapshot.get("autonomy_mode"),
        categories=list(cats),
    )
    return {"instructions": text, "agent_id": agent_id}


@router.patch("/v1/agents/{agent_id}/config")
async def update_agent_config(agent_id: str, body: ConfigBody,
                              request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    await require_step(store, identity.tenant_id, "agent")
    runtime_response = await _forward_config(request, agent_id, identity, body, agent)
    if runtime_response.status_code == 409:
        detail = runtime_response.json()
        raise VerifundError(
            "config_conflict", json.dumps(detail), status_code=409)
    if runtime_response.status_code >= 400:
        raise VerifundError(
            "runtime_error", runtime_response.text, status_code=502)
    snapshot = runtime_response.json()
    await _record_hashes(request, store, identity, agent_id, agent, snapshot)
    await advance_step(store, identity.tenant_id, "catalog")
    return snapshot


@router.patch("/v1/agents/{agent_id}/policies")
async def update_agent_policies(agent_id: str, body: ConfigBody,
                                request: Request) -> dict:
    body = ConfigBody(
        expected_config_version=body.expected_config_version,
        name=body.name, tagline=body.tagline,
        max_discount_bps=body.max_discount_bps,
        autonomy_mode=body.autonomy_mode,
        tool_allowlist=body.tool_allowlist,
    )
    return await update_agent_config(agent_id, body, request)


@router.post("/v1/seller/catalog/import")
async def catalog_import_route(body: CatalogImportBody, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    store = request.app.state.tenancy
    await require_step(store, identity.tenant_id, "config")
    if len(body.document.encode(errors="ignore")) > 2 * 1024 * 1024:
        raise VerifundError("too_large", "document exceeds 2 MB", status_code=413)
    runtime_response = await _call_runtime(
        request, "/internal/catalog/import",
        headers={"x-org-id": identity.tenant_id},
        json_body={"document": body.document,
                   "replace_catalog": body.replace_catalog})
    if runtime_response.status_code == 422:
        detail = runtime_response.json()
        raise VerifundError(
            "catalog_invalid", "Catalog document failed validation",
            status_code=422,
            details=detail if isinstance(detail, dict) else {"detail": detail},
        )
    if runtime_response.status_code >= 400:
        raise VerifundError(
            "runtime_error", runtime_response.text, status_code=502)
    return runtime_response.json()


@router.post("/v1/agents/{agent_id}/activate")
async def activate_agent_route(agent_id: str, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    # Activation is idempotent for already-active agents so a failed registry
    # publish can be retried without recreating the seller.
    if agent["status"] == "active":
        activated = agent
    else:
        activated = await activate_agent(store, agent_id)
    existing_creds = [c for c in await store.list_credentials(agent_id) if c["status"] == "active"]
    has_call = any(
        "a2a:call" in (c["scopes"] if isinstance(c["scopes"], list) else json.loads(c["scopes"]))
        for c in existing_creds
    )
    if not has_call:
        await issue_credential(store, identity.tenant_id, agent_id, ["a2a:call"])
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    seller_id = (profile or {}).get("seller_id") or agent_id
    settings = request.app.state.settings
    base_url = getattr(settings, "agents_public_base_url", "https://agents.verifund.com")
    # Agent display name: prefer the runtime config, else the profile.
    config_response = await _call_runtime(
        request, f"/internal/agent-configs/{agent_id}",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
        method="GET")
    try:
        snapshot = config_response.json() if config_response.status_code < 400 else {}
    except ValueError:
        snapshot = {}
    name = snapshot.get("name") or (profile or {}).get("name") or "Seller agent"
    allowlist = snapshot.get("tool_allowlist") or []
    card = build_seller_card(
        profile=profile, agent_name=name, agent_id=agent_id,
        allowlist=allowlist, base_url=base_url, seller_id=seller_id)
    registry_url = getattr(settings, "registry_url", "http://127.0.0.1:9100")

    # The shared seller runtime only serves its public card and catalog while
    # the config is active; the registry fetches both during registration.
    runtime_response = await _call_runtime(
        request, f"/internal/agents/{agent_id}/activate",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id})
    if runtime_response.status_code >= 400:
        raise VerifundError(
            "runtime_error",
            f"seller runtime activation failed: {runtime_response.text}",
            status_code=502)

    card_url = f"{base_url.rstrip('/')}/{seller_id}/.well-known/agent-card.json"

    async def _publish(client):
        await publish_seller(
            client,
            seller_id=seller_id,
            card_url=card_url,
            organization_id=identity.tenant_id,
        )

    try:
        factory = getattr(request.app.state, "registry_client_factory", None)
        if factory is not None:
            async with factory() as client:
                await _publish(client)
        else:
            async with httpx.AsyncClient(base_url=registry_url,
                                         timeout=httpx.Timeout(10.0)) as client:
                await _publish(client)
        published = True
    except Exception as e:  # noqa: BLE001 - activation already committed; retry activation to republish
        published = False
        await store.record_audit(
            scope="agents", organization_id=identity.tenant_id,
            actor_user_id=identity.user_id, actor_type="system",
            action="agent.publish_failed", resource_id=agent_id,
            payload={"error": str(e)})
    return {"agent_id": agent_id, "status": activated["status"],
            "registry_published": published, "card": card}


@router.get("/v1/agents/{agent_id}/status")
async def agent_status_route(agent_id: str, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    latest = await store.latest_test_run(agent_id)
    base: dict = {
        "agent_id": agent["id"],
        "status": agent["status"],
        "name": agent.get("name"),
        "policy_version": agent.get("policy_version"),
        "policy_hash": agent.get("policy_hash"),
        "policy_drift": (agent.get("policy_drift") or "0") == "1",
        "card_hash": agent.get("card_hash"),
        "latest_test_run": latest,
    }
    # Fresh config read from the runtime (never cached): lets the console
    # prefill forms and compare-and-swap on expected_config_version.
    try:
        runtime_response = await _call_runtime(
            request, f"/internal/agent-configs/{agent_id}",
            headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
            method="GET", timeout=5.0)
        if runtime_response.status_code < 400:
            snapshot = runtime_response.json()
            base.update({
                "config_version": snapshot.get("config_version"),
                "policy_version": snapshot.get("policy_version"),
                "policy_hash": snapshot.get("policy_hash"),
                "tool_allowlist": snapshot.get("tool_allowlist") or [],
                "instructions": snapshot.get("instructions") or "",
                "max_discount_bps": snapshot.get("max_discount_bps"),
                "autonomy_mode": snapshot.get("autonomy_mode"),
                "name": snapshot.get("name") or agent.get("name"),
                "tagline": snapshot.get("tagline") or "",
            })
        else:
            base["config_version"] = None
            base["runtime_unreachable"] = True
    except VerifundError:
        base["config_version"] = None
        base["runtime_unreachable"] = True
    return base


@router.get("/v1/agents/{agent_id}/card")
async def agent_card_route(agent_id: str, request: Request) -> dict:
    identity = await require_seller_agent_admin(request)
    agent = await require_own_agent(request, agent_id, identity)
    store = request.app.state.tenancy
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    seller_id = (profile or {}).get("seller_id") or agent_id
    settings = request.app.state.settings
    base_url = getattr(settings, "agents_public_base_url", "https://agents.verifund.com")
    config_response = await _call_runtime(
        request, f"/internal/agent-configs/{agent_id}",
        headers={"x-org-id": identity.tenant_id, "x-agent-id": agent_id},
        method="GET", timeout=5.0)
    try:
        snapshot = config_response.json() if config_response.status_code < 400 else {}
    except ValueError:
        snapshot = {}
    name = snapshot.get("name") or (profile or {}).get("name") or "Seller agent"
    allowlist = snapshot.get("tool_allowlist") or []
    card = build_seller_card(
        profile=profile, agent_name=name, agent_id=agent_id,
        allowlist=allowlist, base_url=base_url, seller_id=seller_id)
    return {"card": card, "card_url": f"{base_url}/{seller_id}/.well-known/agent-card.json",
            "card_hash": agent.get("card_hash")}
