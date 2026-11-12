from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from fastapi import APIRouter, Request
from svix.webhooks import Webhook, WebhookVerificationError

from verifund_control_plane.domain import sha256_hex
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.webhooks import dispatch
from verifund_control_plane.tenancy.sync import apply_clerk_event

router = APIRouter()


def verify_clerk_payload(secret: str, body: bytes, headers: dict[str, str]) -> dict:
    try:
        return Webhook(secret).verify(body, headers)
    except WebhookVerificationError as exc:
        raise VerifundError(
            "unauthorized", "invalid webhook signature", status_code=401
        ) from exc


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    raw = await request.body()
    if settings.is_fake:
        provided = request.headers.get("x-verifund-fake-webhook", "")
        if not settings.fake_webhook_secret or not secrets.compare_digest(
            provided, settings.fake_webhook_secret
        ):
            raise VerifundError(
                "unauthorized", "fake webhook secret is required", status_code=401
            )
        verified = False
    else:
        verified = await request.app.state.payments.verify_webhook(
            request.headers, raw
        )
        if not verified:
            raise VerifundError(
                "unauthorized",
                "PayPal webhook signature is invalid",
                status_code=401,
            )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise VerifundError(
            "invalid_request", "webhook body is not JSON", status_code=400
        ) from exc
    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("event_type") or "")
    if not event_id or not event_type:
        raise VerifundError(
            "invalid_request", "webhook event id and type are required", status_code=400
        )
    resource = payload.get("resource") or {}
    resource_id = resource.get("id")
    repo = request.app.state.repo
    async with repo.transaction() as conn:
        created = await repo.insert_webhook_event(
            conn,
            event_id,
            event_type,
            str(resource_id) if resource_id else None,
            sha256_hex(raw),
            payload,
            settings.mode,
            verified,
        )
    if not created:
        return {"status": "duplicate", "verified": verified}
    try:
        status = await dispatch(request.app.state.service, payload)
    except VerifundError as exc:
        await repo.mark_webhook_event(
            event_id, "failed", last_error=exc.message
        )
        raise
    except Exception as exc:
        await repo.mark_webhook_event(
            event_id, "failed", last_error=type(exc).__name__
        )
        raise VerifundError(
            "internal", "webhook processing failed", status_code=500
        ) from exc
    await repo.mark_webhook_event(event_id, status)
    return {"status": status, "verified": verified}


@router.post("/v1/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, str]:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    event_id = headers.get("svix-id")
    if not event_id:
        raise VerifundError(
            "invalid_request", "svix-id is required", status_code=400
        )
    verifier = getattr(request.app.state, "clerk_verifier", None)
    if verifier is not None:
        event = verifier(body, headers)
    else:
        event = verify_clerk_payload(
            request.app.state.settings.clerk_webhook_secret, body, headers
        )
    repo = request.app.state.repo
    if await repo.webhook_event_exists("clerk", event_id):
        return {"status": "duplicate"}
    await repo.record_webhook_event(
        source="clerk",
        event_id=event_id,
        event_type=event["type"],
        mode="clerk",
        payload=event,
        payload_hash=hashlib.sha256(body).hexdigest(),
        verified=True,
        status="processed",
    )
    await apply_clerk_event(request.app.state.tenancy, event)
    return {"status": "ok"}