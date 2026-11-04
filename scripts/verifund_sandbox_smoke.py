"""Run one real PayPal Sandbox transaction against a running control plane.

This script is manual and gated: it needs `VERIFUND_SANDBOX_SMOKE=1`,
`VERIFUND_MODE=sandbox`, a public HTTPS tunnel, and a human who can pay with
the sandbox buyer account. It never runs in CI.

For a one-shot smoke, start the control plane with
`VERIFUND_INSPECTION_WINDOW_HOURS=0`. Otherwise the script stops after
`VERIFY` and prints the inspection deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verifund_flow import (
    SELLER_ID,
    VerifundFlow,
    award_payload,
    delivery_payload,
    manifest_payload,
)


class StateSource(Protocol):
    def get_state(self, transaction_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SandboxSmokeConfig:
    base_url: str
    ops_token: str
    run_id: str
    fund_timeout_seconds: float
    poll_seconds: float


def smoke_config(
    env: Mapping[str, str] | None = None,
) -> SandboxSmokeConfig:
    values = os.environ if env is None else env
    if values.get("VERIFUND_SANDBOX_SMOKE") != "1":
        raise RuntimeError(
            "set VERIFUND_SANDBOX_SMOKE=1 to run the PayPal sandbox smoke"
        )
    if values.get("VERIFUND_MODE") != "sandbox":
        raise RuntimeError("the sandbox smoke requires VERIFUND_MODE=sandbox")
    ops_token = values.get("VERIFUND_OPS_TOKEN", "")
    if not ops_token:
        raise RuntimeError("VERIFUND_OPS_TOKEN is required")

    try:
        fund_timeout = float(values.get("VERIFUND_SANDBOX_FUND_TIMEOUT", "900"))
        poll_seconds = float(values.get("VERIFUND_SANDBOX_POLL_SECONDS", "3"))
    except ValueError as exc:
        raise RuntimeError("sandbox timeout and polling values must be numbers") from exc
    if fund_timeout <= 0 or poll_seconds < 0:
        raise RuntimeError("sandbox timeout must be positive and polling non-negative")

    return SandboxSmokeConfig(
        base_url=values.get(
            "VERIFUND_CONTROL_PLANE_URL", "http://127.0.0.1:9300"
        ).rstrip("/"),
        ops_token=ops_token,
        run_id=values.get("VERIFUND_SANDBOX_RUN_ID", "run-verifund-sandbox"),
        fund_timeout_seconds=fund_timeout,
        poll_seconds=poll_seconds,
    )


def wait_for_state(
    source: StateSource,
    transaction_id: str,
    *,
    target: str,
    timeout: float,
    poll_seconds: float,
    stop_states: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        current = source.get_state(transaction_id)
        state = str(current.get("state"))
        if state == target:
            return current
        if state in stop_states:
            raise RuntimeError(f"transaction {transaction_id} stopped in {state}")
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"transaction {transaction_id} did not reach {target} "
        f"within {timeout}s: {current}"
    )


def wait_for_funding(
    source: StateSource,
    transaction_id: str,
    *,
    timeout: float,
    poll_seconds: float,
) -> dict[str, Any]:
    return wait_for_state(
        source,
        transaction_id,
        target="FUNDED",
        timeout=timeout,
        poll_seconds=poll_seconds,
        stop_states={"CANCELED", "FAILED"},
    )


def wait_for_payout(
    source: StateSource,
    transaction_id: str,
    *,
    timeout: float,
    poll_seconds: float,
) -> dict[str, Any]:
    return wait_for_state(
        source,
        transaction_id,
        target="RELEASED",
        timeout=timeout,
        poll_seconds=poll_seconds,
        stop_states={"REVIEW_REQUIRED", "CANCELED", "FAILED"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--payout-timeout",
        type=float,
        default=float(os.environ.get("VERIFUND_SANDBOX_PAYOUT_TIMEOUT", "600")),
    )
    args = parser.parse_args(argv)

    try:
        config = smoke_config()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_id = args.run_id or config.run_id
    console_base_url = os.environ.get(
        "VERIFUND_CONSOLE_BASE_URL", "http://127.0.0.1:3000"
    )

    with VerifundFlow(
        config.base_url,
        config.ops_token,
        console_base_url=console_base_url,
    ) as flow:
        request = award_payload(run_id)
        award = flow.award(run_id)
        transaction_id = str(award["transaction_id"])
        flow.accept(award)
        flow.approve(award)
        funded = flow.fund(award, run_id=run_id)
        checkout_url = str(funded.get("checkout_url") or "")
        if not checkout_url:
            print("The control plane did not return a checkout URL.", file=sys.stderr)
            return 1

        print(f"transaction: {transaction_id}")
        print(f"agreement:   {award['agreement_hash']}")
        print("Open this PayPal sandbox checkout and pay as the buyer:")
        print(checkout_url)
        print(
            f"Waiting up to {config.fund_timeout_seconds:.0f}s for FUNDED...",
            flush=True,
        )
        try:
            state = wait_for_funding(
                flow,
                transaction_id,
                timeout=config.fund_timeout_seconds,
                poll_seconds=config.poll_seconds,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(f"Funding did not complete: {exc}", file=sys.stderr)
            return 1

        funding = state.get("funding") or {}
        capture_id = funding.get("capture_id")
        print(f"FUNDED capture: {capture_id}")

        purchase = flow.purchase_order(award, request)
        print(f"purchase order: {purchase.get('state')}")

        now = datetime.now(UTC)
        tracking = "VF-SANDBOX-TRK-1"
        flow.upload_evidence(
            award,
            "shipment_manifest",
            manifest_payload(
                seller_id=SELLER_ID,
                agreement_hash=str(award["agreement_hash"]),
                tracking_number=tracking,
                shipped_at=now - timedelta(hours=2),
            ),
            "shipment-manifest.json",
        )
        flow.upload_evidence(
            award,
            "delivery_confirmation",
            delivery_payload(
                tracking_number=tracking,
                delivered_at=now - timedelta(hours=1),
            ),
            "delivery-confirmation.json",
        )

        verification = flow.verify(transaction_id)
        verification_state = verification.get("state")
        print(f"verify: {verification_state}")
        if verification_state == "REVIEW_REQUIRED":
            reasons = (verification.get("verification") or {}).get("reasons")
            print(f"Verification requires review: {reasons}", file=sys.stderr)
            return 1
        if verification_state == "VERIFICATION_PENDING":
            deadline = (verification.get("deadlines") or {}).get("inspection")
            print(
                "Evidence is complete, but the inspection window is open "
                f"until {deadline}.",
                file=sys.stderr,
            )
            print(
                "Restart the control plane with "
                "VERIFUND_INSPECTION_WINDOW_HOURS=0 for a one-shot smoke.",
                file=sys.stderr,
            )
            return 3

        released = flow.release(transaction_id)
        if released.get("state") != "RELEASED":
            print(
                "Waiting up to "
                f"{args.payout_timeout:.0f}s for the sandbox payout...",
                flush=True,
            )
            try:
                state = wait_for_payout(
                    flow,
                    transaction_id,
                    timeout=args.payout_timeout,
                    poll_seconds=config.poll_seconds,
                )
            except (RuntimeError, TimeoutError) as exc:
                print(f"Payout did not complete: {exc}", file=sys.stderr)
                return 1
        else:
            state = released

        receipt = flow.get_receipt(transaction_id)
        payout = state.get("payout") or {}
        print(
            json.dumps(
                {
                    "transaction_id": transaction_id,
                    "state": state.get("state"),
                    "agreement_hash": award["agreement_hash"],
                    "capture_id": capture_id,
                    "payout_batch_id": payout.get("batch_id"),
                    "payout_item_id": payout.get("item_id"),
                    "receipt_payload_hash": receipt.get("payload_hash"),
                    "receipt_signature": receipt.get("signature"),
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
