from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.verifund_e2e import e2e_environment, playwright_command
from scripts.verifund_flow import (
    AMOUNT_CENTS,
    award_payload,
    delivery_payload,
    manifest_payload,
    summarize_ledger,
)
from scripts.verifund_smoke import smoke_environment

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_award_payload_is_balanced():
    payload = award_payload("run-1")

    assert payload["run_id"] == "run-1"
    assert payload["amount_cents"] == AMOUNT_CENTS
    assert sum(item["quantity"] for item in payload["line_items"]) == (payload["quantity"])
    assert (
        sum(
            (item["unit_price_cents"] + item["warranty_addon_cents"]) * item["quantity"]
            for item in payload["line_items"]
        )
        + payload["shipping_cents"]
        == payload["amount_cents"]
    )


def test_manifest_and_delivery_payloads_are_policy_ready():
    manifest = manifest_payload(
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        tracking_number="TRK-1",
        shipped_at=NOW - timedelta(hours=2),
    )
    delivery = delivery_payload(tracking_number="TRK-1", delivered_at=NOW - timedelta(hours=1))

    assert manifest["tracking_number"] == delivery["tracking_number"] == "TRK-1"
    assert manifest["agreement_hash"] == "a" * 64
    assert datetime.fromisoformat(delivery["delivered_at"]) < NOW


def test_summarize_ledger_balances_held_funds():
    rows = [
        {"account": "platform_cash", "debit_cents": 123400, "credit_cents": 0},
        {"account": "held_funds", "debit_cents": 0, "credit_cents": 123400},
        {"account": "held_funds", "debit_cents": 123400, "credit_cents": 0},
        {"account": "seller_paid", "debit_cents": 0, "credit_cents": 123400},
    ]

    summary = summarize_ledger(rows)

    assert summary["held_funds"] == {"debit": 123400, "credit": 123400}
    assert summary["platform_cash"] == {"debit": 123400, "credit": 0}
    assert summary["seller_paid"] == {"debit": 0, "credit": 123400}
    assert sum(item["debit"] for item in summary.values()) == sum(
        item["credit"] for item in summary.values()
    )


def test_smoke_environment_is_isolated_and_fake(tmp_path: Path):
    env = smoke_environment(tmp_path, port=9399)

    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_PORT"] == "9399"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_RECONCILER_ENABLED"] == "false"
    assert str(tmp_path / "verifund.db") in env["VERIFUND_DATABASE_URL"]
    assert env["VERIFUND_EVIDENCE_DIR"] == str(tmp_path / "evidence")


def test_e2e_environment_forces_fake_mode():
    env = e2e_environment({"PATH": "/bin"})

    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_CONTROL_PLANE_URL"] == "http://127.0.0.1:9300"
    assert playwright_command() == [
        "pnpm",
        "exec",
        "playwright",
        "test",
        "e2e/verifund.spec.ts",
    ]
