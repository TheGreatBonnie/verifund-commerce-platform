"""Run the complete local MarketMesh stack with one command."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from config import (
    ROOT,
    SELLERS,
    admin_token,
    buyer_a2a_url,
    buyer_agui_url,
    buyer_url,
    console_port,
    llm_mode,
    nebius_api_key,
    nebius_base_url,
    nebius_model,
    orchestrator_agui_url,
    orchestrator_port,
    orchestrator_url,
    registry_url,
    seller_tokens_json,
)

DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / ".dev-logs"
PID_FILE = ROOT / ".dev-pids.json"


@dataclass
class Child:
    name: str
    process: subprocess.Popen
    log_path: Path
    url: str | None = None


def _env_value(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _base_env(mode: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOST": _env_value("HOST", "127.0.0.1"),
            "MARKETMESH_LLM_MODE": mode,
            "PYTHONUNBUFFERED": "1",
        }
    )
    if mode == "live":
        env["NEBIUS_API_KEY"] = nebius_api_key()
        env["BASE_URL"] = nebius_base_url()
        env["MODEL"] = nebius_model()
    return env


def _registry_port() -> int:
    raw = _env_value("REGISTRY_PORT", "9105")
    return int(raw) if raw.isdigit() else 9105


def _registry_database() -> str:
    return _env_value(
        "REGISTRY_DATABASE_URL",
        "sqlite+aiosqlite:///./data/registry.db",
    )


def _buyer_database() -> str:
    return _env_value(
        "BUYER_DATABASE_URL", "sqlite+aiosqlite:///./data/buyer.db"
    )


def _checkpoint_path() -> str:
    return _env_value("BUYER_CHECKPOINT_PATH", "./data/buyer-checkpoints.db")


def _children_alive(path: Path) -> list[int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    alive = []
    for service in data.get("services", []):
        pid = service.get("pid")
        if not isinstance(pid, int):
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        alive.append(pid)
    return alive


def _terminate(children: list[Child]) -> None:
    for child in children:
        if child.process.poll() is not None:
            continue
        try:
            os.killpg(child.process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            child.process.terminate()

    deadline = time.monotonic() + 8
    for child in children:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            child.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                child.process.kill()


def stop_stack() -> int:
    if not PID_FILE.exists():
        print("No local MarketMesh stack is recorded.")
        return 0
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        print("Removed an unreadable process record.")
        return 0

    pids = [
        service["pid"]
        for service in data.get("services", [])
        if isinstance(service.get("pid"), int)
    ]
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not any(_pid_alive(pid) for pid in pids):
            break
        time.sleep(0.2)

    for pid in pids:
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    PID_FILE.unlink(missing_ok=True)
    print(f"Stopped {len(pids)} local services.")
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tail(path: Path, lines: int = 25) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log output)"
    return "\n".join(content[-lines:])


def wait_for_http(
    name: str,
    url: str,
    *,
    timeout: float,
    process: subprocess.Popen | None = None,
    log_path: Path | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            detail = _tail(log_path) if log_path else "(no log)"
            raise RuntimeError(
                f"{name} exited with code {process.returncode} before it "
                f"became ready.\n{detail}"
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.4)
    detail = _tail(log_path) if log_path else "(no log)"
    raise RuntimeError(
        f"Timed out waiting for {name} at {url}: {last_error}\n{detail}"
    )


def start_child(
    name: str,
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path = ROOT,
    url: str | None = None,
) -> Child:
    log_path = LOG_DIR / f"{name}.log"
    handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    finally:
        handle.close()
    print(f"  started {name:<12} pid {process.pid} -> {log_path.name}")
    return Child(name=name, process=process, log_path=log_path, url=url)


def registry_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": str(_registry_port()),
            "REGISTRY_PORT": str(_registry_port()),
            "DATABASE_URL": _registry_database(),
            "REGISTRY_DATABASE_URL": _registry_database(),
            "REGISTRY_ADMIN_TOKEN": admin_token(),
            "ALLOWED_CARD_HOSTS": allowed_card_hosts_json(),
        }
    )
    return env


def seller_environment(mode: str, seller) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": str(seller.port),
            "SELLER_PORT": str(seller.port),
            "PROFILE_PATH": str(seller.profile_path),
            "PUBLIC_BASE_URL": seller.base_url,
            "SELLER_TOKEN": seller.token,
            "DATABASE_URL": seller.database_url,
            "SELLER_DATABASE_URL": seller.database_url,
        }
    )
    return env


def buyer_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": _env_value("BUYER_PORT", "9100"),
            "BUYER_PORT": _env_value("BUYER_PORT", "9100"),
            "REGISTRY_URL": registry_url(),
            "BUYER_DATABASE_URL": _buyer_database(),
            "BUYER_CHECKPOINT_PATH": _checkpoint_path(),
            "BUYER_SELLER_TOKENS": seller_tokens_json(),
            "BUYER_CONSOLE_API_TOKEN": _env_value(
                "BUYER_CONSOLE_API_TOKEN", "dev-console"
            ),
            "ALLOWED_CARD_HOSTS": allowed_card_hosts_json(),
        }
    )
    return env


def allowed_card_hosts_json() -> str:
    configured = _env_value(
        "ALLOWED_CARD_HOSTS",
        '["127.0.0.1","localhost","northwind","circuitforge","aurora"]',
    )
    try:
        configured_hosts = json.loads(configured)
    except (json.JSONDecodeError, TypeError):
        configured_hosts = None
    hosts = (
        {host for host in configured_hosts if isinstance(host, str)}
        if isinstance(configured_hosts, list)
        else {"127.0.0.1", "localhost"}
    )
    for seller in SELLERS:
        hostname = urlsplit(seller.base_url).hostname
        if hostname:
            hosts.add(hostname)
    return json.dumps(sorted(hosts))


def seller_auth_environment() -> dict[str, str]:
    return {seller.token_var: seller.token for seller in SELLERS}


def orchestrator_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": str(orchestrator_port()),
            "ORCHESTRATOR_PORT": str(orchestrator_port()),
            "ORCHESTRATOR_URL": orchestrator_url(),
            "ORCHESTRATOR_AGUI_URL": orchestrator_agui_url(),
            "BUYER_A2A_URL": buyer_a2a_url(),
            "SELLER_URLS": ",".join(seller.base_url for seller in SELLERS),
            "COPILOTKIT_AGENT_MODEL": f"openai:{nebius_model()}",
            "OPENAI_BASE_URL": nebius_base_url(),
        }
    )
    env.update(seller_auth_environment())
    if mode == "live":
        env["OPENAI_API_KEY"] = nebius_api_key()
    return env


def console_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "BUYER_AGUI_URL": buyer_agui_url(),
            "BUYER_API_URL": buyer_url(),
            "BUYER_CONSOLE_API_TOKEN": _env_value(
                "BUYER_CONSOLE_API_TOKEN", "dev-console"
            ),
            "ORCHESTRATOR_AGUI_URL": orchestrator_agui_url(),
            "REGISTRY_URL": registry_url(),
            "NEXT_TELEMETRY_DISABLED": "1",
            "COPILOTKIT_TELEMETRY_DISABLED": "true",
        }
    )
    env.update(seller_auth_environment())
    return env


def run_seed(mode: str) -> None:
    print("Seeding seller catalogs and registry...")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed.py")],
        cwd=ROOT,
        env=_base_env(mode),
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Seed failed. Inspect .dev-logs for the running services."
        )


def _write_pids(children: list[Child], mode: str) -> None:
    payload = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "services": [
            {
                "name": child.name,
                "pid": child.process.pid,
                "url": child.url,
                "log": str(child.log_path),
            }
            for child in children
        ],
    }
    PID_FILE.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _resolve_mode(scripted: bool) -> str:
    if scripted:
        return "scripted"
    mode = llm_mode()
    if mode not in {"scripted", "live"}:
        print(f"Unknown MARKETMESH_LLM_MODE={mode!r}; using scripted mode.")
        return "scripted"
    if mode == "live" and not nebius_api_key():
        print(
            "No usable Nebius key; running the deterministic scripted demo.\n"
            "Set NEBIUS_API_KEY to use live agents."
        )
        return "scripted"
    return mode


def run_stack(scripted: bool) -> int:
    mode = _resolve_mode(scripted)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        alive = _children_alive(PID_FILE)
        if alive:
            print(
                "The dev stack is already running. Use `make down` first.\n"
                f"Live PIDs: {', '.join(map(str, alive))}"
            )
            return 1
        PID_FILE.unlink(missing_ok=True)

    npm = shutil.which("npm")
    if npm is None:
        print("npm is required to run the console.", file=sys.stderr)
        return 1

    children: list[Child] = []
    interrupted = False
    print(f"MarketMesh local stack · {mode} mode")

    try:
        registry = start_child(
            "registry",
            [sys.executable, "-m", "registry"],
            env=registry_environment(mode),
            url=f"{registry_url().rstrip('/')}/health",
        )
        children.append(registry)
        wait_for_http(
            "registry",
            f"{registry_url().rstrip('/')}/health",
            timeout=30,
            process=registry.process,
            log_path=registry.log_path,
        )

        for seller in SELLERS:
            child = start_child(
                seller.log_name,
                [sys.executable, "-m", "seller_agent"],
                env=seller_environment(mode, seller),
                url=f"{seller.base_url}/health",
            )
            children.append(child)
            wait_for_http(
                seller.log_name,
                f"{seller.base_url}/health",
                timeout=30,
                process=child.process,
                log_path=child.log_path,
            )

        run_seed(mode)

        buyer = start_child(
            "buyer",
            [sys.executable, "-m", "buyer_agent"],
            env=buyer_environment(mode),
            url=f"{buyer_url().rstrip('/')}/health",
        )
        children.append(buyer)
        wait_for_http(
            "buyer",
            f"{buyer_url().rstrip('/')}/health",
            timeout=45,
            process=buyer.process,
            log_path=buyer.log_path,
        )

        orchestrator = start_child(
            "orchestrator",
            [sys.executable, "-m", "orchestrator_agent"],
            env=orchestrator_environment(mode),
            url=f"{orchestrator_url().rstrip('/')}/health",
        )
        children.append(orchestrator)
        wait_for_http(
            "orchestrator",
            f"{orchestrator_url().rstrip('/')}/health",
            timeout=45,
            process=orchestrator.process,
            log_path=orchestrator.log_path,
        )

        console = start_child(
            "console",
            [
                npm,
                "run",
                "dev",
                "--",
                "--port",
                str(console_port()),
            ],
            env=console_environment(mode),
            cwd=ROOT / "apps/console",
            url=f"http://127.0.0.1:{console_port()}",
        )
        children.append(console)
        wait_for_http(
            "console",
            f"http://127.0.0.1:{console_port()}",
            timeout=90,
            process=console.process,
            log_path=console.log_path,
        )

        _write_pids(children, mode)
        print("\nMarketMesh is ready")
        print(f"  Console       http://127.0.0.1:{console_port()}")
        print(f"  Orchestrator  {orchestrator_agui_url()}")
        print(f"  Buyer AG-UI   {buyer_agui_url()}")
        print(f"  Registry      {registry_url().rstrip('/')}/v1/sellers")
        for seller in SELLERS:
            print(f"  {seller.seller_id:<13} {seller.base_url}")
        print("\nPress Ctrl-C to stop the stack. Logs: .dev-logs/")

        while True:
            for child in children:
                code = child.process.poll()
                if code is not None:
                    raise RuntimeError(
                        f"{child.name} exited unexpectedly with code {code}.\n"
                        f"{_tail(child.log_path)}"
                    )
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopping MarketMesh...")
    except RuntimeError as exc:
        print(f"\nStartup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate(children)
        PID_FILE.unlink(missing_ok=True)
        if interrupted:
            print("Stopped.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "stop"],
        default="start",
        help="start the stack (default) or stop a recorded stack",
    )
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="force the deterministic scripted demo regardless of .env",
    )
    args = parser.parse_args()
    if args.command == "stop":
        return stop_stack()
    return run_stack(args.scripted)


if __name__ == "__main__":
    raise SystemExit(main())
