"""Start the demo stack and print the sample procurement brief."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
LOG_DIR = ROOT / ".dev-logs"
BRIEF = (
    "Buy 12 Nimbus NC-700 ANC headsets for our team. "
    "Budget $3,400, delivery within 14 days, 24-month warranty, "
    "30-day returns. Prefer a sustainability-certified seller."
)


def console_url() -> str:
    port = os.environ.get("CONSOLE_PORT", "3000")
    return f"http://127.0.0.1:{port}"


def is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_until_ready(url: str, dev: subprocess.Popen, *, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if dev.poll() is not None:
            raise RuntimeError(
                f"dev stack exited with code {dev.returncode}; "
                "see .dev-logs/run_demo.out"
            )
        if is_ready(url):
            return
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verifund", choices=["off", "fake", "sandbox"], default=None
    )
    args = parser.parse_args(argv)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    url = console_url()

    if is_ready(url):
        print(f"MarketMesh is already running at {url}")
    else:
        mode = os.environ.get("MARKETMESH_LLM_MODE", "scripted").lower()
        key = os.environ.get("NEBIUS_API_KEY", "").strip()
        command = [sys.executable, str(ROOT / "scripts/dev.py")]
        if args.verifund:
            command.extend(["--verifund", args.verifund])
        if mode != "live" or not key:
            print("No usable Nebius key; running scripted demo.")
            command.append("--scripted")
        else:
            print("Starting live Nebius demo.")

        log_path = LOG_DIR / "run_demo.out"
        handle = log_path.open("a", encoding="utf-8")
        try:
            dev = subprocess.Popen(
                command,
                cwd=ROOT,
                env=os.environ.copy(),
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            handle.close()
        print(f"Stack logs: {log_path.relative_to(ROOT)}")
        wait_until_ready(url, dev)

    print(f"\nOpen {url} and click “Run sample brief”.")
    print(f"\nSample brief:\n  {BRIEF}")
    print("\nApprove the recommended award to place the order.")
    print("Stop the stack with `make down`.")
    settlement_mode = args.verifund or os.environ.get("VERIFUND_MODE", "sandbox")
    if settlement_mode in {"fake", "sandbox"}:
        print(
            "Review the agreement in chat, approve funding, complete checkout, "
            "then review evidence and approve payout release separately."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Demo failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
