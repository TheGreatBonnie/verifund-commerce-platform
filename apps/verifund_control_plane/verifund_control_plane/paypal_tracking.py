"""Outbound PayPal tracker sync (plan Task 28)."""

from __future__ import annotations

from typing import Any, Protocol


class PayPalTrackingClient(Protocol):
    async def sync(
        self,
        *,
        transaction_id: str,
        capture_id: str,
        tracking_number: str,
        carrier: str,
        items: list[dict[str, Any]],
        carrier_name_other: str | None = None,
    ) -> str: ...


class FakePayPalTracking:
    """In-memory idempotent tracker used by tests and local development."""

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], str] = {}

    async def sync(
        self,
        *,
        transaction_id: str,
        capture_id: str,
        tracking_number: str,
        carrier: str = "OTHER",
        items: list[dict[str, Any]] | None = None,
        carrier_name_other: str | None = None,
    ) -> str:
        key = (capture_id, tracking_number)
        if key not in self._ids:
            self._ids[key] = f"{capture_id}-{tracking_number}"
        return self._ids[key]
