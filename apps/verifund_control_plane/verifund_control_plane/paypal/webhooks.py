from __future__ import annotations

from decimal import Decimal
from typing import Any

from verifund_control_plane.paypal.port import CaptureResult

CAPTURE_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.DECLINED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
}
REFUND_EVENTS = {
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
}


def capture_order_id(resource: dict[str, Any]) -> str | None:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    value = related.get("order_id")
    return str(value) if value else None


def _up_capture_id(resource: dict[str, Any]) -> str | None:
    for link in resource.get("links") or []:
        if link.get("rel") == "up" and link.get("href"):
            return str(link["href"]).rstrip("/").rsplit("/", 1)[-1]
    return None


def _cents(value: Any) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


def parse_capture(
    resource: dict[str, Any], *, order_id: str, capture_id: str | None = None,
    status: str | None = None,
) -> CaptureResult:
    amount = resource.get("amount") or {}
    return CaptureResult(
        order_id=order_id,
        capture_id=capture_id or str(resource.get("id") or ""),
        status=status or str(resource.get("status") or "UNKNOWN"),
        amount_cents=_cents(amount.get("value", "0")),
        currency=str(amount.get("currency_code") or ""),
        raw=resource,
    )


async def dispatch(service, event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    if event_type not in CAPTURE_EVENTS:
        return "ignored"
    order_id = capture_order_id(resource)
    if order_id:
        capture = parse_capture(resource, order_id=order_id)
        applied = await service.apply_capture_by_order(
            order_id, capture, actor="webhook:paypal"
        )
        return "processed" if applied else "unmatched"
    if event_type in REFUND_EVENTS:
        capture_id = _up_capture_id(resource)
        if not capture_id:
            return "unmatched"
        record = await service.repo.find_transaction_by_capture_id(capture_id)
        if record is None:
            return "unmatched"
        order_id = str(
            (record.funding or {}).get("provider_order_id") or ""
        )
        capture = parse_capture(
            resource,
            order_id=order_id,
            capture_id=capture_id,
            status="REFUNDED" if event_type.endswith("REFUNDED") else "REVERSED",
        )
        await service.apply_capture(
            record.transaction_id, capture, actor="webhook:paypal"
        )
        return "processed"
    return "unmatched"