from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from a2a.types.a2a_pb2 import Role, TaskState
from commerce_core.a2a_parts import make_message
from commerce_core.contracts import RFQ, RFQConstraints, RFQPreferences
from commerce_core.extension import wrap_payload
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from seller_agent.catalog_import import CatalogImportError, parse_catalog_document
from seller_agent.planner import ScriptedSellerPlanner
from seller_agent.shared_store import (
    ConfigConflict,
    ConfigUpsert,
    OrgScopedStore,
    TenantContextError,
)

router = APIRouter(prefix="/internal")


def _require_internal_token(request: Request) -> None:
    settings = request.app.state.settings
    token = request.headers.get("x-internal-token", "")
    if not settings.internal_api_token or not hmac.compare_digest(
        token, settings.internal_api_token,
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "internal_auth",
                    "message": "bad internal credential"})


def _org(request: Request) -> str:
    org = (request.headers.get("x-org-id") or "").strip()
    if not org:
        raise HTTPException(
            status_code=400,
            detail={"code": "org_required", "message": "x-org-id required"})
    return org


def _agent(request: Request) -> str | None:
    return request.headers.get("x-agent-id")


@router.get("/health")
async def internal_health() -> dict:
    return {"status": "ok"}


def get_store(request: Request, org: str, agent: str | None = None) -> OrgScopedStore:
    engine = getattr(request.app.state, "shared_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "shared_runtime_unavailable",
                    "message": "shared engine not initialized"})
    return OrgScopedStore(engine, organization_id=org, agent_id=agent)


class AgentConfigBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    tagline: str | None = Field(default=None, max_length=256)
    instructions: str | None = Field(default=None, max_length=4096)
    max_discount_bps: int | None = Field(default=None, ge=0, le=10_000)
    autonomy_mode: str | None = Field(
        default=None, pattern="^(read_only|assisted|policy_bounded)$")
    tool_allowlist: list[str] | None = None
    expected_config_version: int | None = Field(default=None, ge=1)


class CatalogImportBody(BaseModel):
    document: str = Field(min_length=2, max_length=2 * 1024 * 1024)
    replace_catalog: bool = False


class TestSuiteBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    credential: str = Field(min_length=1)
    revoked_credential: str = Field(min_length=1)


@router.post("/agent-configs")
async def upsert_agent_config(body: AgentConfigBody, request: Request,
                              _=Depends(_require_internal_token)):  # noqa: B008
    org = _org(request)
    if org != body.organization_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "org_mismatch",
                    "message": "x-org-id does not match payload"})
    store = get_store(request, org, body.agent_id)
    try:
        snapshot = await store.upsert_config(
            body.agent_id,
            ConfigUpsert(
                name=body.name, tagline=body.tagline,
                instructions=body.instructions,
                max_discount_bps=body.max_discount_bps,
                autonomy_mode=body.autonomy_mode,
                tool_allowlist=body.tool_allowlist,
                expected_config_version=body.expected_config_version),
            seller_id=body.seller_id,
            name=body.name or body.seller_id,
            tagline=body.tagline or "",
        )
    except ConfigConflict as conflict:
        raise HTTPException(
            status_code=409,
            detail={"code": "config_conflict",
                    "config_version": conflict.current_version})
    return snapshot.__dict__


@router.post("/catalog/import")
async def import_catalog(body: CatalogImportBody, request: Request,
                         _=Depends(_require_internal_token)):  # noqa: B008
    org = _org(request)
    agent = _agent(request)
    try:
        products = parse_catalog_document(body.document)
    except CatalogImportError as e:
        return JSONResponse(status_code=422, content={"errors": e.errors})
    store = get_store(request, org, agent)
    counts = await store.import_products(
        [p.model_dump(mode="json") for p in products],
        replace=body.replace_catalog)
    return {"inserted": counts["inserted"], "updated": counts["updated"],
            "replaced": counts["replaced"], "errors": []}


@router.get("/agent-configs/{agent_id}")
async def get_agent_config(agent_id: str, request: Request,
                           _=Depends(_require_internal_token)):  # noqa: B008
    org = _org(request)
    store = get_store(request, org, agent_id)
    snapshot = await store.get_config(agent_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_agent", "message": "unknown agent"})
    return snapshot.__dict__


async def _verify(settings, request: Request, token: str, *,
                  purpose: str = "a2a:call") -> dict[str, Any] | None:
    """Verify a machine credential against the control plane.

    Injected `request.app.state.credential_verifier` short-circuits the
    HTTP hop (used by integration tests running everything in-process).
    Otherwise POSTs to {verifund_url}/v1/agent-credentials/verify.
    """
    injected = getattr(request.app.state, "credential_verifier", None)
    if injected is not None:
        return await injected(token, purpose=purpose)
    if settings.verifund_mode == "off":
        return None
    async with httpx.AsyncClient(base_url=settings.verifund_url,
                                 timeout=httpx.Timeout(5.0)) as client:
        response = await client.post(
            "/v1/agent-credentials/verify",
            json={"token": token, "purpose": purpose})
        if response.status_code == 200:
            return response.json()
        return None


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


@router.post("/test-suite")
async def test_suite(body: TestSuiteBody, request: Request,
                     _=Depends(_require_internal_token)):  # noqa: B008
    org = _org(request)
    store = get_store(request, org, body.agent_id)
    settings = request.app.state.settings

    checks: list[dict[str, Any]] = []

    # 1. Agent credential verifies (active).
    verified = await _verify(settings, request, body.credential,
                              purpose="a2a:test")
    auth_ok = bool(verified) and verified.get("status") == "active"
    checks.append(_check(
        "auth", auth_ok,
        f"credential verified for agent {verified.get('agent_id')}"
        if auth_ok else "credential rejected or not active"))

    # 2. Catalog returns a known SKU for this org.
    sku = await store.first_sku()
    checks.append(_check(
        "catalog", sku is not None,
        f"first SKU available: {sku}" if sku
        else "catalog is empty for this organization"))

    # 3. Pricing bounds: every product satisfies floor <= initial <= list.
    try:
        policy = await store.load_policy()
        pricing_ok = len(policy.catalog()) > 0 and all(
            (
                p.floor_unit_price_cents is not None
                and p.initial_unit_price_cents is not None
                and p.list_unit_price_cents is not None
                and p.floor_unit_price_cents <= p.initial_unit_price_cents
                and p.initial_unit_price_cents <= p.list_unit_price_cents
            )
            for p in policy.catalog()
        )
        pricing_detail = (
            f"{len(policy.catalog())} products within floor/initial/list bounds"
            if pricing_ok else "at least one product violates price bounds")
    except TenantContextError as e:
        pricing_ok, pricing_detail = False, str(e)
    checks.append(_check("pricing", pricing_ok, pricing_detail))

    # 4. A2A round trip: an in-process RFQ turn returns an offer for this org.
    a2a_ok = False
    a2a_detail = "not executed"
    try:
        policy = await store.load_policy()
        from seller_agent.service import SellerService as _Svc
        service = _Svc(
            store=store,
            policy=policy,
            planner=ScriptedSellerPlanner(),
            mandate=await store.load_mandate(),
            settlement=None,
            settlement_enabled=False,
            auto_evidence=False,
            review_store=None,
        )
        product = policy.catalog()[0]
        rfq = RFQ(
            request_id=f"rfq-check-{uuid.uuid4().hex[:8]}",
            run_id="test-suite",
            category=policy.categories[0],
            product_hint=product.name,
            product_sku=product.sku,
            quantity=1,
            required_by=datetime.now(UTC) + timedelta(days=7),
            constraints=RFQConstraints(min_warranty_months=0, min_returns_days=0),
            preferences=RFQPreferences(),
        )
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        context_id = f"ctx_{uuid.uuid4().hex[:12]}"
        message = make_message(
            role=Role.ROLE_USER,
            text="Need one unit.",
            context_id=context_id,
            task_id=task_id,
            envelope=wrap_payload("rfq", rfq),
        )
        turn = await service.handle_turn(task_id, context_id, message)
        from commerce_core.a2a_parts import part_value
        offer_found = False
        for artifact in turn.artifacts:
            for part in artifact.parts:
                payload = part_value(part)
                if (
                    isinstance(payload, dict)
                    and isinstance(payload.get("payload"), dict)
                    and payload["payload"].get("offer_id")
                ):
                    offer_found = True
        a2a_ok = bool(offer_found) and turn.task_state in (
            TaskState.TASK_STATE_INPUT_REQUIRED,
            TaskState.TASK_STATE_COMPLETED,
        )
        a2a_detail = ("mediated RFQ round trip returned an offer"
                      if a2a_ok else "RFQ turn completed without an offer artifact")
    except Exception as e:  # noqa: BLE001 - the check must report failures, never crash
        a2a_ok, a2a_detail = False, f"in-process RFQ failed: {e}"
    checks.append(_check("a2a", a2a_ok, a2a_detail))

    # 5. Authority bound: computed budget respects floor; policy_bounded enforced.
    config = await store.get_config(body.agent_id)
    authority_ok = False
    authority_detail = "seller config not found"
    if config is not None:
        policy = await store.load_policy()
        product = policy.catalog()[0]
        initial = product.initial_unit_price_cents
        floor = product.floor_unit_price_cents
        max_discount = config.max_discount_bps
        agent_max_unit = max(
            floor or 0,
            (initial or 0) * (10_000 - (max_discount or 0)) // 10_000,
        )
        deep_discount = (initial or 0) // 2
        authority_ok = (
            config.autonomy_mode == "policy_bounded"
            and deep_discount < (floor or 0)
            and agent_max_unit >= (floor or 0))
        authority_detail = (
            f"policy_bounded; deep discount {deep_discount}c < floor {floor}c; "
            f"max concession unit {agent_max_unit}c ≥ floor")
    checks.append(_check("authority", authority_ok, authority_detail))

    # 6. Revoked credential stops passing.
    revoked = await _verify(settings, request, body.revoked_credential,
                             purpose="a2a:test")
    revoked_ok = revoked is None or revoked.get("status") != "active"
    checks.append(_check(
        "revocation", revoked_ok,
        "revoked credential denied" if revoked_ok else "revoked credential still verifies"))

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}
