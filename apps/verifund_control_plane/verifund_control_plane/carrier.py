"""Carrier adapter protocol and mock implementation.

Provides normalized, carrier-authoritative shipment facts for shipped flows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizedCarrierEvent:
    provider_event_id: str
    normalized_status: str
    event_at: datetime
    weight_g: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofOfDelivery:
    delivered_at: datetime
    status: str
    recipient_reference: str | None = None
    signature_reference: str | None = None
    pod_reference: str | None = None
    weight_g: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CarrierRecord:
    tracking_number: str
    status: str  # "delivered" | "in_transit" | "unknown"
    delivered_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class CarrierUnavailable(Exception):
    """Raised by an adapter when the upstream carrier cannot be reached."""


class CarrierAdapter(Protocol):
    async def register_tracking(self, shipment: dict[str, Any]) -> dict[str, Any]: ...

    async def get_tracking_events(
        self, tracking_number: str, *, scenario: str | None = None
    ) -> list[NormalizedCarrierEvent]: ...

    async def get_proof_of_delivery(
        self, tracking_number: str, *, scenario: str | None = None
    ) -> ProofOfDelivery | None: ...


class MockCarrierAdapter:
    """Deterministic carrier adapter for sandbox scenarios."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self._registered: dict[str, dict[str, Any]] = {}

    async def register_tracking(self, shipment: dict[str, Any]) -> dict[str, Any]:
        tracking_number = str(shipment.get("tracking_number") or "")
        self._registered[tracking_number] = dict(shipment)
        return {"tracking_number": tracking_number, "status": "registered"}

    def _scenario_for(self, tracking_number: str, scenario: str | None) -> str:
        if scenario:
            return scenario
        shipment = self._registered.get(tracking_number, {})
        if shipment.get("scenario"):
            return str(shipment["scenario"])
        # Allow SANDBOX-<scenario> or SANDBOX_<scenario> style keys.
        upper = tracking_number.upper()
        for key in (
            "happy_path",
            "specs_mismatch",
            "packing_photo_missing",
            "weight_anomaly",
            "never_delivers",
            "dispute_seller_wins",
            "dispute_buyer_wins",
        ):
            if key.upper() in upper:
                return key
        return "happy_path"

    def _base(self, tracking_number: str) -> datetime:
        # Stable base derived from tracking number so events are deterministic
        # and far enough in the past that default inspection windows elapse.
        seed = sum(ord(c) for c in tracking_number) % 60
        now = self.clock()
        return (now - timedelta(hours=48, minutes=seed)).replace(microsecond=0)

    async def get_tracking_events(
        self, tracking_number: str, *, scenario: str | None = None
    ) -> list[NormalizedCarrierEvent]:
        scenario_key = self._scenario_for(tracking_number, scenario)
        base = self._base(tracking_number)
        shipment = self._registered.get(tracking_number, {})
        pickup_weight = int(shipment.get("weight_expected_g") or 2100)
        if scenario_key == "weight_anomaly":
            pickup_weight = max(1, pickup_weight // 10)

        def ev(offset_min: int, status: str, provider_suffix: str, weight_g: int | None = None, **payload: Any):
            return NormalizedCarrierEvent(
                provider_event_id=f"{tracking_number}:{provider_suffix}",
                normalized_status=status,
                event_at=base + timedelta(minutes=offset_min),
                weight_g=weight_g,
                payload={"tracking_number": tracking_number, **payload},
            )

        events = [ev(0, "LABEL_CREATED", "label")]
        if scenario_key == "never_delivers":
            events.extend(
                [
                    ev(5, "PICKED_UP", "pickup", weight_g=pickup_weight),
                    ev(30, "IN_TRANSIT", "transit"),
                ]
            )
            return events

        events.append(ev(5, "PICKED_UP", "pickup", weight_g=pickup_weight))
        events.append(ev(30, "IN_TRANSIT", "transit"))
        events.append(ev(60, "OUT_FOR_DELIVERY", "ofd"))
        if scenario_key in {"happy_path", "specs_mismatch", "packing_photo_missing", "weight_anomaly", "dispute_seller_wins", "dispute_buyer_wins"}:
            events.append(
                ev(
                    90,
                    "DELIVERED_SIGNED",
                    "delivered",
                    weight_g=pickup_weight,
                    recipient_reference="J. DOE",
                    signature_reference=f"SIG-{tracking_number[-6:]}",
                    pod_reference=f"POD-{tracking_number[-6:]}",
                )
            )
        return events

    async def get_proof_of_delivery(
        self, tracking_number: str, *, scenario: str | None = None
    ) -> ProofOfDelivery | None:
        events = await self.get_tracking_events(tracking_number, scenario=scenario)
        for event in reversed(events):
            if event.normalized_status in {"DELIVERED", "DELIVERED_SIGNED"}:
                payload = event.payload or {}
                return ProofOfDelivery(
                    delivered_at=event.event_at,
                    status=event.normalized_status,
                    recipient_reference=payload.get("recipient_reference"),
                    signature_reference=payload.get("signature_reference"),
                    pod_reference=payload.get("pod_reference"),
                    weight_g=event.weight_g,
                    payload=payload,
                )
        return None


# Backward-compatible names for the previous unreferenced stub.
CarrierClient = CarrierAdapter
FakeCarrier = MockCarrierAdapter
