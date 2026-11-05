"""Carrier aggregator adapter (plan Task 14).

A small protocol plus an in-memory/fake implementation. Real aggregators
(EasyPost/Shippo/PayPal Tracking) land behind ``CarrierClient`` in Milestone E.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class CarrierRecord:
    tracking_number: str
    status: str  # "delivered" | "in_transit" | "unknown"
    delivered_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class CarrierUnavailable(Exception):
    """Raised by an adapter when the upstream carrier cannot be reached."""


class CarrierClient(Protocol):
    async def fetch(self, tracking_number: str) -> CarrierRecord: ...


class FakeCarrier:
    """In-memory carrier used by tests and local development.

    ``raise_on_call`` simulates a persistent outage; the adapter retries with
    backoff and then returns an ``unknown`` record instead of propagating the
    failure (a carrier outage is never a permanent block).
    """

    def __init__(
        self,
        *,
        records: dict[str, CarrierRecord] | None = None,
        raise_on_call: bool = False,
        max_retries: int = 3,
        base_delay_seconds: float = 0.0,
        on_outage: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self._records = records or {}
        self._raise_on_call = raise_on_call
        self._max_retries = max(1, max_retries)
        self._base_delay = base_delay_seconds
        self._on_outage = on_outage
        self.alerts: list[tuple[str, str]] = []

    async def fetch(self, tracking_number: str) -> CarrierRecord:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                if self._raise_on_call:
                    raise CarrierUnavailable(
                        f"carrier unavailable for {tracking_number}"
                    )
                record = self._records.get(tracking_number)
                if record is None:
                    return CarrierRecord(
                        tracking_number=tracking_number, status="unknown"
                    )
                return record
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._max_retries - 1 and self._base_delay > 0:
                    await asyncio.sleep(self._base_delay * (2 ** attempt))
        # Outage exhausted: alert ops and degrade to "unknown".
        message = str(last_error) if last_error is not None else "unknown error"
        self.alerts.append((tracking_number, message))
        if self._on_outage is not None and last_error is not None:
            try:
                result = self._on_outage(tracking_number, last_error)
                if isinstance(result, Awaitable):
                    await result
            except Exception:  # noqa: BLE001, S110
                pass
        return CarrierRecord(
            tracking_number=tracking_number,
            status="unknown",
            error=message,
        )
