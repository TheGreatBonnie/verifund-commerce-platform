"""Run the scripted local stack and the Playwright acceptance tests."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_URL = f"http://127.0.0.1:{os.environ.get('CONSOLE_PORT', '3000')}"
FRAMES = ROOT / "tests/fixtures/frames"
SAMPLE_FRAMES = ROOT / "docs/sample-frames"


def wait_for(url: str, *, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}")


def copy_frames() -> None:
    SAMPLE_FRAMES.mkdir(parents=True, exist_ok=True)
    if not FRAMES.exists():
        return
    for source in sorted(FRAMES.glob("*.json")):
        target = SAMPLE_FRAMES / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"sample frame: {target.relative_to(ROOT)}")


def stop_stack() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev.py"), "stop"],
        cwd=ROOT,
        check=False,
    )


def main() -> int:
    npm = shutil.which("npm")
    npx = shutil.which("npx")
    if npm is None or npx is None:
        print("npm and npx are required for the browser tests.", file=sys.stderr)
        return 1

    stop_stack()
    env = os.environ.copy()
    env["MARKETMESH_LLM_MODE"] = "scripted"
    env["CONSOLE_PORT"] = os.environ.get("CONSOLE_PORT", "3000")

    dev = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/dev.py"), "--scripted"],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        wait_for(CONSOLE_URL)
        subprocess.run(
            [npx, "playwright", "install", "chromium"],
            cwd=ROOT / "apps/console",
            env=env,
            check=False,
        )
        result = subprocess.run(
            [npx, "playwright", "test"],
            cwd=ROOT / "apps/console",
            env=env,
            check=False,
        )
        copy_frames()
        return result.returncode
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
