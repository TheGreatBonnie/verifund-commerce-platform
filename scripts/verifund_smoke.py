"""Run a headless fake-mode Verifund lifecycle against a temporary control plane."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import ROOT
from scripts.verifund_flow import (
    AMOUNT_CENTS,
    SELLER_ID,
    VerifundFlow,
    summarize_ledger,
)

EXPECTED_LEDGER = {
    "platform_cash": {"debit": AMOUNT_CENTS, "credit": 0},
    "held_funds": {"debit": AMOUNT_CENTS, "credit": AMOUNT_CENTS},
    "seller_paid": {"debit": 0, "credit": AMOUNT_CENTS},
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def smoke_environment(root: Path, *, port: int) -> dict[str, str]:
    return {
        "VERIFUND_MODE": "fake",
        "HOST": "127.0.0.1",
        "VERIFUND_PORT": str(port),
        "VERIFUND_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "VERIFUND_CONSOLE_BASE_URL": "http://127.0.0.1:3000",
        "VERIFUND_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'verifund.db'}",
        "VERIFUND_EVIDENCE_DIR": str(root / "evidence"),
        "VERIFUND_INSPECTION_WINDOW_HOURS": "0",
        "VERIFUND_RECONCILER_ENABLED": "false",
        "VERIFUND_OPS_TOKEN": "smoke-ops",
        "VERIFUND_SELLER_TOKEN_SECRET": "smoke-seller-token-secret",
        "VERIFUND_LINK_SECRET": "smoke-link-secret",
        "VERIFUND_SELLER_PAYOUT_EMAILS": json.dumps({SELLER_ID: "seller-northwind@example.com"}),
    }


def wait_for(url: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {url}")


def ledger_rows(database: Path, transaction_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select account, debit_cents, credit_cents from ledger_entries "
            "where transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="run-verifund-smoke")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="verifund-smoke-") as tmp:
        root = Path(tmp)
        port = free_port()
        env = os.environ.copy()
        env.update(smoke_environment(root, port=port))
        log_path = root / "control-plane.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "verifund_control_plane"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for(f"http://127.0.0.1:{port}/health")
                with VerifundFlow(f"http://127.0.0.1:{port}", "smoke-ops") as flow:
                    result = flow.run(args.run_id)
                summary = summarize_ledger(ledger_rows(root / "verifund.db", result.transaction_id))
                if summary != EXPECTED_LEDGER:
                    raise AssertionError(f"unexpected ledger: {summary!r}")
                if result.state != "RELEASED":
                    raise AssertionError(f"unexpected final state: {result.state}")
                if not result.receipt.get("verified"):
                    raise AssertionError("receipt signature did not verify")
                print(
                    json.dumps(
                        {
                            "transaction_id": result.transaction_id,
                            "state": result.state,
                            "agreement_hash": result.agreement_hash,
                            "receipt_payload_hash": result.receipt["payload_hash"],
                            "ledger": summary,
                        },
                        indent=2,
                    )
                )
                return 0
            except Exception:
                log.flush()
                print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
