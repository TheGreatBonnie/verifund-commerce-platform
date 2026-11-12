from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import (
    Message,
    Role,
    SendMessageRequest,
)
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.cards import DEFAULT_CARD_HOSTS, fetch_agent_card

# Hosts whose agent cards this process may fetch. The local stack answers on
# loopback hostnames; a deployed gateway publishes its cards on its public
# host, so the orchestrator configures this from ALLOWED_CARD_HOSTS at
# startup rather than relying on the local-only defaults.
_card_hosts: tuple[str, ...] = DEFAULT_CARD_HOSTS


def set_card_hosts(hosts: tuple[str, ...]) -> None:
    """Set the hosts this process may fetch agent cards from."""
    global _card_hosts
    _card_hosts = tuple(hosts)


async def _a2a_send(base_url: str, message: Message, token: str | None = None) -> list:
    card = await fetch_agent_card(
        f"{base_url.rstrip('/')}/.well-known/agent-card.json",
        allowed_hosts=_card_hosts,
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    http = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0, connect=5.0))
    client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)
    frames = []
    try:
        async for event in client.send_message(SendMessageRequest(message=message)):
            frames.append(event)
    finally:
        await client.close()
        await http.aclose()
    return frames


def _buyer_response(frames: list) -> dict[str, Any] | None:
    """Extract the buyer's JSON status response from its A2A task events."""
    response = None
    for frame in frames:
        kind = frame.WhichOneof("payload")
        if kind == "status_update":
            message = frame.status_update.status.message
        elif kind == "task":
            message = frame.task.status.message
        else:
            continue
        for part in message.parts:
            if not part.HasField("text"):
                continue
            try:
                value = json.loads(part.text)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(value, dict) and value.get("status"):
                response = value
    return response


async def _resolve_caller_token(
    control_plane_url: str,
    buyer_internal_token: str,
    *,
    timeout_seconds: float = 10.0,
) -> str:
    """Exchange a fresh buyer caller credential from the control plane.

    The credential is minted on demand (``vf_agent_*``, hash-stored) and
    presented as the A2A bearer to the seller. The seller verifies it via
    ``POST /v1/agent-credentials/verify``; a valid token therefore has
    ``agent_id = agent_marketmesh_buyer`` and scope ``a2a:call``.
    """
    if not control_plane_url or not buyer_internal_token:
        raise ValueError("control plane token exchange is not configured")
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{control_plane_url.rstrip('/')}/v1/internal/buyer-token",
            headers={"X-Internal-Token": buyer_internal_token},
        )
        response.raise_for_status()
        body = response.json()
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("control plane returned no caller token")
    return token


def _resolve_seller_token(
    seller_card_url: str, seller_token: str | None, seller_id: str | None = None
) -> str:
    """Legacy synchronous resolver.

    Only an explicitly supplied, non-default token (e.g. in tests) is
    honoured. Static ``BUYER_AGENT_TOKEN`` / ``SELLER_*_TOKEN`` environment
    variables are no longer a source of truth; callers must pass an
    explicitly exchanged token or use :func:`_resolve_caller_token`.
    """
    if seller_token and seller_token != "dev-seller":
        return seller_token
    raise ValueError(
        f"No seller authentication token configured for {seller_card_url}; "
        "exchange a caller token from the control plane"
    )


SETTLEMENT_TOKEN_KEYS = {
    "settlement_token",
    "seller_token",
    "authorization",
    "x-marketmesh-internal-token",
}


def _redact_settlement(value: Any, token: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in SETTLEMENT_TOKEN_KEYS
                else _redact_settlement(item, token)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_settlement(item, token) for item in value]
    if token and isinstance(value, str) and token in value:
        return value.replace(token, "[REDACTED]")
    return value


def _inject_settlement_token(
    envelope: dict[str, Any], token: str
) -> dict[str, Any]:
    injected = deepcopy(envelope)
    payload = injected.get("payload")
    if isinstance(payload, dict):
        payload["settlement_token"] = token
    else:
        injected["settlement_token"] = token
    return injected


async def _resolve_settlement_token(
    buyer_internal_url: str,
    buyer_internal_token: str,
    ref: dict[str, Any],
    *,
    timeout_seconds: float = 10.0,
) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{buyer_internal_url.rstrip('/')}/internal/settlement/seller-token",
            headers={"x-marketmesh-internal-token": buyer_internal_token},
            json=ref,
        )
        response.raise_for_status()
        token = response.json().get("seller_token")
    if not isinstance(token, str) or not token:
        raise ValueError("buyer returned no seller token")
    return token


async def mediate_seller_call(
    buyer_task_id: str,
    seller_card_url: str,
    buyer_a2a_url: str,
    seller_request: dict[str, Any] | None = None,
    seller_token: str | None = None,
    seller_id: str | None = None,
    seller_task_id: str | None = None,
    seller_context_id: str | None = None,
    buyer_context_id: str | None = None,
    settlement_secret_ref: dict[str, Any] | None = None,
    buyer_internal_url: str | None = None,
    buyer_internal_token: str | None = None,
    buyer_internal_timeout_seconds: float = 10.0,
    control_plane_url: str | None = None,
) -> dict[str, Any]:
    """Mediate a single buyer seller-call pause through the orchestrator."""
    try:
        request_envelope = seller_request or {}
        resolved_token: str | None = None
        if settlement_secret_ref:
            if not buyer_internal_url or not buyer_internal_token:
                raise ValueError(
                    "buyer internal settlement endpoint is not configured"
                )
            resolved_token = await _resolve_settlement_token(
                buyer_internal_url,
                buyer_internal_token,
                settlement_secret_ref,
                timeout_seconds=buyer_internal_timeout_seconds,
            )
            request_envelope = _inject_settlement_token(
                request_envelope, resolved_token
            )
        seller_base = seller_card_url.split("/.well-known")[0]
        msg = make_message(
            role=Role.ROLE_USER,
            text="Orchestrator-mediated seller request.",
            context_id=seller_context_id or buyer_task_id,
            task_id=seller_task_id,
            envelope=request_envelope if request_envelope else None,
        )
        # Prefer an explicit token (tests); otherwise exchange a fresh caller
        # credential from the control plane. Static env tokens are never used.
        if seller_token:
            token = _resolve_seller_token(seller_card_url, seller_token, seller_id)
        else:
            token = await _resolve_caller_token(
                control_plane_url or "",
                buyer_internal_token or "",
                timeout_seconds=buyer_internal_timeout_seconds,
            )
        frames = await _a2a_send(seller_base, msg, token=token)

        offers: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []
        response_task_id = seller_task_id or ""
        response_context_id = seller_context_id or buyer_task_id
        for frame in frames:
            kind = frame.WhichOneof("payload")
            artifacts = []
            if kind == "artifact_update":
                response_task_id = frame.artifact_update.task_id or response_task_id
                response_context_id = frame.artifact_update.context_id or response_context_id
                artifacts = [frame.artifact_update.artifact]
            elif kind == "task":
                response_task_id = frame.task.id or response_task_id
                response_context_id = frame.task.context_id or response_context_id
                artifacts = list(frame.task.artifacts)
            elif kind == "status_update":
                response_task_id = frame.status_update.task_id or response_task_id
                response_context_id = frame.status_update.context_id or response_context_id
            for art in artifacts:
                for part in art.parts:
                    val = part_value(part)
                    if not isinstance(val, dict):
                        continue
                    if "payload" in val and "schema" in val:
                        val = val["payload"]
                    if isinstance(val, dict):
                        if val.get("offer_id") and not val.get("order_id"):
                            offers.append(val)
                        elif val.get("order_id"):
                            orders.append(val)

        seller_result = {
            "offers": offers,
            "orders": orders,
            "order": orders[0] if orders else None,
            "task_id": response_task_id,
            "context_id": response_context_id,
        }

        resume_msg = make_message(
            role=Role.ROLE_USER,
            text=json.dumps({"seller_result": seller_result, "task_id": buyer_task_id}),
            context_id=buyer_context_id or buyer_task_id,
        )
        buyer_frames = await _a2a_send(buyer_a2a_url, resume_msg)
        buyer_response = _buyer_response(buyer_frames)

        return {
            "resumed": True,
            "seller_result": _redact_settlement(seller_result, resolved_token),
            "buyer_response": _redact_settlement(buyer_response, resolved_token),
            "seller_communication": {
                "seller_id": seller_id,
                "seller_card_url": seller_card_url,
                "request": _redact_settlement(request_envelope, resolved_token),
                "response": _redact_settlement(seller_result, resolved_token),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: seller mediation failed"}
