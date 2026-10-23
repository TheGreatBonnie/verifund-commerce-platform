from __future__ import annotations

import json
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


async def mediate_seller_call(
    buyer_task_id: str,
    seller_card_url: str,
    buyer_a2a_url: str,
    seller_request: dict[str, Any] | None = None,
    seller_token: str = "dev-seller",
) -> dict[str, Any]:
    """Mediate a single buyer seller-call pause through the orchestrator."""
    try:
        request_envelope = seller_request or {}
        seller_base = seller_card_url.split("/.well-known")[0]
        msg = make_message(
            role=Role.ROLE_USER,
            text="Orchestrator-mediated seller request.",
            context_id=buyer_task_id,
            envelope=request_envelope if request_envelope else None,
        )
        frames = await _a2a_send(seller_base, msg, token=seller_token)

        offers: list[dict[str, Any]] = []
        for frame in frames:
            kind = frame.WhichOneof("payload")
            artifacts = []
            if kind == "artifact_update":
                artifacts = [frame.artifact_update.artifact]
            elif kind == "task":
                artifacts = list(frame.task.artifacts)
            for art in artifacts:
                for part in art.parts:
                    val = part_value(part)
                    if not isinstance(val, dict):
                        continue
                    if "payload" in val and "schema" in val:
                        val = val["payload"]
                    if isinstance(val, dict) and val.get("offer_id"):
                        offers.append(val)

        seller_result = {
            "offers": offers,
            "task_id": buyer_task_id,
            "context_id": buyer_task_id,
        }

        resume_msg = make_message(
            role=Role.ROLE_USER,
            text=json.dumps({"seller_result": seller_result, "task_id": buyer_task_id}),
            context_id=buyer_task_id,
        )
        await _a2a_send(buyer_a2a_url, resume_msg)

        return {"resumed": True, "seller_result": seller_result}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}