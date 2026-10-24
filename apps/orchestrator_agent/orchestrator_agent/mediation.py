from __future__ import annotations

import json
import os
from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import (
    Message,
    Role,
    SendMessageRequest,
)
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.cards import fetch_agent_card


async def _a2a_send(base_url: str, message: Message, token: str | None = None) -> list:
    card = await fetch_agent_card(f"{base_url.rstrip('/')}/.well-known/agent-card.json")
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


def _resolve_seller_token(seller_card_url: str, seller_token: str | None) -> str:
    # Prefer an explicitly supplied, non-default token (e.g. tests).
    if seller_token and seller_token != "dev-seller":
        return seller_token
    # Otherwise resolve from per-seller config by port.
    try:
        port = seller_card_url.split("://", 1)[-1].split("/", 1)[0].split(":")[-1]
    except Exception:  # noqa: BLE001
        port = ""
    port_map = {
        "9201": os.environ.get("SELLER_NORTHWIND_TOKEN", "dev-northwind"),
        "9202": os.environ.get("SELLER_CIRCUITFORGE_TOKEN", "dev-circuitforge"),
        "9203": os.environ.get("SELLER_AURORA_TOKEN", "dev-aurora"),
    }
    return port_map.get(port, os.environ.get("SELLER_TOKEN", "dev-seller"))


async def mediate_seller_call(
    buyer_task_id: str,
    seller_card_url: str,
    buyer_a2a_url: str,
    seller_request: dict[str, Any] | None = None,
    seller_token: str | None = None,
    seller_id: str | None = None,
    seller_task_id: str | None = None,
    seller_context_id: str | None = None,
) -> dict[str, Any]:
    """Mediate a single buyer seller-call pause through the orchestrator."""
    try:
        request_envelope = seller_request or {}
        seller_base = seller_card_url.split("/.well-known")[0]
        msg = make_message(
            role=Role.ROLE_USER,
            text="Orchestrator-mediated seller request.",
            context_id=seller_context_id or buyer_task_id,
            task_id=seller_task_id,
            envelope=request_envelope if request_envelope else None,
        )
        token = _resolve_seller_token(seller_card_url, seller_token)
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
            context_id=buyer_task_id,
        )
        buyer_frames = await _a2a_send(buyer_a2a_url, resume_msg)
        buyer_response = _buyer_response(buyer_frames)

        return {
            "resumed": True,
            "seller_result": seller_result,
            "buyer_response": buyer_response,
            "seller_communication": {
                "seller_id": seller_id,
                "seller_card_url": seller_card_url,
                "request": request_envelope,
                "response": seller_result,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
