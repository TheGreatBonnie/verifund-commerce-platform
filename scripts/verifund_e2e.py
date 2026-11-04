"""Run the fake Verifund stack and its Playwright acceptance test."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_URL = f"http://127.0.0.1:{os.environ.get('CONSOLE_PORT', '3000')}"
CONTROL_PLANE_URL = f"http://127.0.0.1:{os.environ.get('VERIFUND_PORT', '9300')}"


def e2e_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(
        {
            "MARKETMESH_LLM_MODE": "scripted",
            "VERIFUND_MODE": "fake",
            "VERIFUND_INSPECTION_WINDOW_HOURS": "0",
            "VERIFUND_CONTROL_PLANE_URL": CONTROL_PLANE_URL,
            "VERIFUND_CONSOLE_BASE_URL": CONSOLE_URL,
        }
    )
    env.setdefault("VERIFUND_AGENT_PORT", "9301")
    env.setdefault("VERIFUND_AGENT_INTERNAL_TOKEN", "dev-verifund-agent-internal")
    env.setdefault("CONSOLE_PORT", os.environ.get("CONSOLE_PORT", "3000"))
    return env


def playwright_command() -> list[str]:
    return ["pnpm", "exec", "playwright", "test", "e2e/verifund.spec.ts"]


def wait_for(url: str, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {url}")


def stop_stack() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/dev.py"), "stop"], cwd=ROOT, check=False)


def main() -> int:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        print("pnpm is required for the Verifund browser test.", file=sys.stderr)
        return 1
    stop_stack()
    env = e2e_environment()
    dev = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/dev.py"), "--scripted", "--verifund", "fake"],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        wait_for(CONSOLE_URL)
        subprocess.run(
            [pnpm, "exec", "playwright", "install", "chromium"],
            cwd=ROOT / "apps/console",
            env=env,
            check=False,
        )
        return subprocess.run(
            playwright_command(), cwd=ROOT / "apps/console", env=env, check=False
        ).returncode
    finally:
        if dev.poll() is None:
            try:
                os.killpg(dev.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                dev.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(dev.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stop_stack()


if __name__ == "__main__":
    raise SystemExit(main())
