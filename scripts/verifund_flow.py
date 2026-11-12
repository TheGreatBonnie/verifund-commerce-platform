"""Drive one Verifund transaction through the control-plane HTTP API."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import httpx

AMOUNT_CENTS = 123400
SHIPPING_CENTS = 3400
QUANTITY = 12
UNIT_PRICE_CENTS = 10000
SELLER_ID = "northwind-audio"
BUYER_ID = "buyer-demo"
DEFAULT_RUN_ID = "run-verifund-smoke"


def award_payload(run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "buyer_id": BUYER_ID,
        "seller_id": SELLER_ID,
        "offer_id": "offer-northwind-1",
        "currency": "USD",
        "amount_cents": AMOUNT_CENTS,
        "shipping_cents": SHIPPING_CENTS,
        "quantity": QUANTITY,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": QUANTITY,
                "unit_price_cents": UNIT_PRICE_CENTS,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


def manifest_payload(
    *, seller_id: str, agreement_hash: str, tracking_number: str, shipped_at: datetime
) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "seller_id": seller_id,
        "agreement_hash": agreement_hash,
        "tracking_number": tracking_number,
        "carrier": "Verifund Logistics",
        "shipped_at": shipped_at.isoformat(),
        "items": [{"sku": "NC-700", "quantity": QUANTITY}],
    }


def delivery_payload(*, tracking_number: str, delivered_at: datetime) -> dict[str, Any]:
    return {
        "confirmation_version": 1,
        "tracking_number": tracking_number,
        "carrier": "Verifund Logistics",
        "delivered_at": delivered_at.isoformat(),
        "recipient": "Demo Buyer",
    }


def summarize_ledger(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = summary.setdefault(str(row["account"]), {"debit": 0, "credit": 0})
        bucket["debit"] += int(row["debit_cents"])
        bucket["credit"] += int(row["credit_cents"])
    return summary


def encode_payload(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class FlowResult:
    transaction_id: str
    agreement_hash: str
    state: str
    receipt: dict[str, Any]


class VerifundFlow:
    def __init__(
        self,
        base_url: str,
        ops_token: str,
        *,
        console_base_url: str = "http://127.0.0.1:3000",
        timeout: float = 20.0,
        client: httpx.Client | None = None,
        settlement_internal_token: str | None = None,
        seller_organization_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.console_base_url = console_base_url.rstrip("/")
        self.ops_token = ops_token
        self.settlement_internal_token = settlement_internal_token
        self.seller_organization_id = seller_organization_id
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _ops_headers(self, actor: str, idempotency_key: str | None) -> dict[str, str]:
        headers = {"authorization": f"Bearer {self.ops_token}", "x-verifund-actor": actor}
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return headers

    def _ops(
        self,
        method: str,
        path: str,
        *,
        actor: str = "buyer-agent",
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        response = self._client.request(
            method, path, headers=self._ops_headers(actor, idempotency_key), **kwargs
        )
        response.raise_for_status()
        return response

    def award(self, run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
        return self._ops(
            "POST", "/awards", json=award_payload(run_id), idempotency_key=f"award:{run_id}"
        ).json()

    def review(
        self, award: Mapping[str, Any], *, buyer_task_id: str = "task-verifund-buyer"
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/buyer-review",
            json={
                "buyer_id": BUYER_ID,
                "agreement_version": award["agreement_version"],
                "agreement_hash": award["agreement_hash"],
                "decision": "accepted",
                "note": "fake lifecycle buyer review",
                "buyer_task_id": buyer_task_id,
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
            idempotency_key=f"buyer-review:{transaction_id}",
        ).json()

    def accept(
        self, award: Mapping[str, Any], *, seller_task_id: str = "task-verifund"
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/accept",
            json={
                "seller_id": SELLER_ID,
                "agreement_hash": award["agreement_hash"],
                "accepted_total_cents": AMOUNT_CENTS,
                "seller_task_id": seller_task_id,
                "accepted_at": datetime.now(UTC).isoformat(),
            },
            idempotency_key=f"accept:{transaction_id}",
        ).json()

    def approve(
        self, award: Mapping[str, Any], *, approved_by: str = "console:reviewer"
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/approve",
            actor="console:reviewer",
            json={
                "approval_id": f"approval-{transaction_id}",
                "approved_by": approved_by,
                "approved_at": datetime.now(UTC).isoformat(),
                "note": "verifund flow",
                "agreement_hash": award["agreement_hash"],
            },
            idempotency_key=f"approve:{transaction_id}",
        ).json()

    def fund(self, award: Mapping[str, Any], *, run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return_url = f"{self.console_base_url}/runs/{run_id}"
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/fund",
            json={
                "agreement_hash": award["agreement_hash"],
                "return_url": return_url,
                "cancel_url": return_url,
            },
            idempotency_key=f"fund:{transaction_id}",
        ).json()

    def complete_checkout(self, checkout_url: str) -> str:
        response = self._client.post(
            checkout_url, data={"action": "approve"}, follow_redirects=False
        )
        if response.status_code not in {302, 303}:
            raise RuntimeError(
                f"fake checkout returned {response.status_code}: {response.text[:200]}"
            )
        return response.headers.get("location", "")

    def purchase_order(
        self,
        award: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        tracking_number: str = "VF-TRK-1",
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        now = datetime.now(UTC)
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/purchase-order",
            json={
                "agreement_hash": award["agreement_hash"],
                "seller_order_id": f"MM-{transaction_id[-6:].upper()}",
                "offer_id": request["offer_id"],
                "quantity": request["quantity"],
                "total_cents": request["amount_cents"],
                "currency": request["currency"],
                "tracking_number": tracking_number,
                "carrier": "Verifund Logistics",
                "reserved_at": now.isoformat(),
                "eta": (now + timedelta(days=int(request["delivery_days"]))).isoformat(),
                "line_items": [
                    {
                        "sku": item["sku"],
                        "quantity": item["quantity"],
                        "unit_price_cents": item["unit_price_cents"],
                        "warranty_addon_cents": item["warranty_addon_cents"],
                    }
                    for item in request["line_items"]
                ],
            },
            idempotency_key=f"po:{transaction_id}",
        ).json()

    def upload_evidence(
        self, award: Mapping[str, Any], kind: str, payload: Mapping[str, Any], filename: str
    ) -> dict[str, Any]:
        # ``kind`` here is the requirement identity (e.g. ``shipment_manifest``);
        # migrated seller routes require ``requirement_id``, not ``kind``.
        transaction_id = str(award["transaction_id"])
        if not self.settlement_internal_token or not self.seller_organization_id:
            raise RuntimeError(
                "upload_evidence requires settlement_internal_token and "
                "seller_organization_id for internal service auth"
            )
        response = self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers={
                "x-verifund-internal-token": self.settlement_internal_token,
                "x-seller-org-id": self.seller_organization_id,
                "x-seller-id": str(award.get("seller_id", SELLER_ID)),
            },
            data={
                "requirement_id": kind,
                "note": f"verifund flow {kind}",
                "captured_at": datetime.now(UTC).isoformat(),
            },
            files={"file": (filename, encode_payload(payload), "application/json")},
        )
        response.raise_for_status()
        return response.json()

    def verify(self, transaction_id: str) -> dict[str, Any]:
        return self._ops("POST", f"/transactions/{transaction_id}/verify", json={}).json()

    def release(
        self, transaction_id: str, *, released_by: str = "console:reviewer"
    ) -> dict[str, Any]:
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/release",
            actor="console:reviewer",
            json={"released_by": released_by, "note": "verifund flow", "override": False},
        ).json()

    def get_state(self, transaction_id: str) -> dict[str, Any]:
        return self._ops(
            "GET", f"/transactions/{transaction_id}/state", actor="console:reviewer"
        ).json()

    def get_receipt(self, transaction_id: str) -> dict[str, Any]:
        return self._ops(
            "GET", f"/transactions/{transaction_id}/receipt", actor="console:reviewer"
        ).json()

    def wait_for_state(
        self, transaction_id: str, state: str, *, timeout: float = 30.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        current: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            current = self.get_state(transaction_id)
            if current["state"] == state:
                return current
            time.sleep(0.2)
        raise TimeoutError(f"transaction {transaction_id} did not reach {state}: {current}")

    def run(self, run_id: str = DEFAULT_RUN_ID) -> FlowResult:
        request = award_payload(run_id)
        award = self.award(run_id)
        self.review(award)
        self.accept(award)
        self.approve(award)
        funded = self.fund(award, run_id=run_id)
        self.complete_checkout(str(funded["checkout_url"]))
        transaction_id = str(award["transaction_id"])
        self.wait_for_state(transaction_id, "FUNDED")
        self.purchase_order(award, request)
        now = datetime.now(UTC)
        self.upload_evidence(
            award,
            "shipment_manifest",
            manifest_payload(
                seller_id=SELLER_ID,
                agreement_hash=str(award["agreement_hash"]),
                tracking_number="VF-TRK-1",
                shipped_at=now - timedelta(hours=2),
            ),
            "shipment-manifest.json",
        )
        self.upload_evidence(
            award,
            "delivery_confirmation",
            delivery_payload(tracking_number="VF-TRK-1", delivered_at=now - timedelta(hours=1)),
            "delivery-confirmation.json",
        )
        self.verify(transaction_id)
        self.release(transaction_id)
        state = self.wait_for_state(transaction_id, "RELEASED")
        return FlowResult(
            transaction_id,
            str(award["agreement_hash"]),
            str(state["state"]),
            self.get_receipt(transaction_id),
        )
