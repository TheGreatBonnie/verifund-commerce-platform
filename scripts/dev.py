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

try:
    from . import config
    from .config import *
except ImportError:
    import config
    from config import *

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


def seller_environment(mode: str, seller, verifund_mode: str = "sandbox") -> dict[str, str]:
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
            "VERIFUND_MODE": verifund_mode,
        }
    )
    if verifund_mode != "off":
        env["VERIFUND_URL"] = config.verifund_url()
    return env


def buyer_environment(mode: str, verifund_mode: str = "sandbox") -> dict[str, str]:
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
            "VERIFUND_MODE": verifund_mode,
        }
    )
    if verifund_mode != "off":
        env["VERIFUND_URL"] = config.verifund_url()
        env["VERIFUND_OPS_TOKEN"] = config.verifund_ops_token()
        env["BUYER_INTERNAL_TOKEN"] = config.buyer_internal_token()
        env["VERIFUND_AGENT_INTERNAL_TOKEN"] = config.verifund_agent_internal_token()
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


def orchestrator_environment(mode: str, verifund_mode: str = "sandbox") -> dict[str, str]:
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
    if verifund_mode != "off":
        env["BUYER_INTERNAL_URL"] = config.buyer_url()
        env["BUYER_INTERNAL_TOKEN"] = config.buyer_internal_token()
        env["VERIFUND_AGENT_URL"] = config.verifund_agent_url()
        env["VERIFUND_AGENT_CARD_URL"] = config.verifund_agent_card_url()
        env["VERIFUND_AGENT_A2A_TOKEN"] = config.verifund_agent_a2a_token()
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
            "VERIFUND_MODE": "sandbox",
        }
    )
    env.update(seller_auth_environment())
    return env



AGENT_FORBIDDEN_ENV = (
    "VERIFUND_OPS_TOKEN",
    "VERIFUND_SELLER_TOKEN_SECRET",
    "VERIFUND_LINK_SECRET",
    "VERIFUND_RECEIPT_KEYS",
    "VERIFUND_RECEIPT_ACTIVE_KID",
    "BUYER_SELLER_TOKENS",
    "BUYER_INTERNAL_TOKEN",
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "PAYPAL_WEBHOOK_ID",
    "PAYPAL_PLATFORM_EMAIL",
    "PAYPAL_BUYER_EMAIL",
) + tuple(seller.token_var for seller in SELLERS)


def verifund_enabled(mode: str) -> bool:
    return mode != "off"


def verifund_agent_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    for name in AGENT_FORBIDDEN_ENV:
        env.pop(name, None)
    env.update(
        {
            "HOST": _env_value("HOST", "127.0.0.1"),
            "PORT": str(verifund_agent_port()),
            "VERIFUND_AGENT_PORT": str(verifund_agent_port()),
            "VERIFUND_AGENT_URL": verifund_agent_url(),
            "VERIFUND_AGENT_A2A_TOKEN": verifund_agent_a2a_token(),
            "VERIFUND_AGENT_INTERNAL_TOKEN": (
                verifund_agent_internal_token()
            ),
            "VERIFUND_AGENT_TIMEOUT_SECONDS": _env_value(
                "VERIFUND_AGENT_TIMEOUT_SECONDS", "20"
            ),
            "VERIFUND_AGENT_DATABASE_URL": verifund_agent_database_url(),
            "VERIFUND_AGENT_CHECKPOINT_PATH": (
                verifund_agent_checkpoint_path()
            ),
            "BUYER_INTERNAL_URL": buyer_url(),
            "VERIFUND_MODE": mode,
        }
    )
    return env


def verifund_registration_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    for name in AGENT_FORBIDDEN_ENV:
        env.pop(name, None)
    env.pop("VERIFUND_AGENT_A2A_TOKEN", None)
    env.pop("VERIFUND_AGENT_INTERNAL_TOKEN", None)
    env.update(
        {
            "REGISTRY_URL": registry_url(),
            "REGISTRY_ADMIN_TOKEN": admin_token(),
            "VERIFUND_AGENT_ID": "verifund",
            "VERIFUND_AGENT_CARD_URL": verifund_agent_card_url(),
        }
    )
    return env


def control_plane_environment(llm: str, mode: str) -> dict[str, str]:
    env = _base_env(llm)
    env.update(
        {
            "VERIFUND_MODE": mode,
            "HOST": _env_value("HOST", "127.0.0.1"),
            "VERIFUND_PORT": str(verifund_port()),
            "VERIFUND_PUBLIC_BASE_URL": verifund_public_base_url(),
            "VERIFUND_CONSOLE_BASE_URL": verifund_console_base_url(),
            "VERIFUND_ALLOW_PUBLIC_BIND": _env_value(
                "VERIFUND_ALLOW_PUBLIC_BIND", "0"
            ),
            "VERIFUND_OPS_TOKEN": verifund_ops_token(),
            "VERIFUND_SELLER_TOKEN_SECRET": verifund_seller_token_secret(),
            "VERIFUND_LINK_SECRET": verifund_link_secret(),
            "VERIFUND_RECEIPT_KEYS": verifund_receipt_keys(),
            "VERIFUND_RECEIPT_ACTIVE_KID": verifund_receipt_active_kid(),
            "VERIFUND_DATABASE_URL": verifund_database_url(),
            "VERIFUND_EVIDENCE_DIR": verifund_evidence_dir(),
            "VERIFUND_INSPECTION_WINDOW_HOURS": str(
                verifund_inspection_window_hours()
            ),
            "VERIFUND_FAKE_WEBHOOK_SECRET": verifund_fake_webhook_secret(),
            "VERIFUND_SELLER_PAYOUT_EMAILS": seller_payout_emails(),
            "PAYPAL_ENV": paypal_env(),
            "PAYPAL_API_BASE": paypal_api_base(),
            "PAYPAL_CLIENT_ID": _env_value("PAYPAL_CLIENT_ID", ""),
            "PAYPAL_CLIENT_SECRET": _env_value("PAYPAL_CLIENT_SECRET", ""),
            "PAYPAL_WEBHOOK_ID": paypal_webhook_id(),
            "PAYPAL_PLATFORM_EMAIL": paypal_platform_email(),
            "PAYPAL_BUYER_EMAIL": paypal_buyer_email(),
        }
    )
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


def _write_pids(
    children: list[Child], mode: str, verifund_mode: str = "sandbox"
) -> None:
    payload = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "verifund_mode": verifund_mode,
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


def run_stack(scripted: bool, settlement_mode: str = "off") -> int:
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
    print(f"MarketMesh local stack · {mode} mode · Verifund {settlement_mode}")

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

        if verifund_enabled(settlement_mode):
            control_plane = start_child(
                "verifund",
                [sys.executable, "-m", "verifund_control_plane"],
                env=control_plane_environment(mode, settlement_mode),
                url=f"{verifund_url()}/health",
            )
            children.append(control_plane)
            wait_for_http(
                "verifund",
                f"{verifund_url()}/health",
                timeout=45,
                process=control_plane.process,
                log_path=control_plane.log_path,
            )
            if (
                settlement_mode == "sandbox"
                and not verifund_public_base_url().startswith("https://")
            ):
                print(
                    "Sandbox needs a public HTTPS tunnel; "
                    "VERIFUND_PUBLIC_BASE_URL is not HTTPS."
                )

        for seller in SELLERS:
            child = start_child(
                seller.log_name,
                [sys.executable, "-m", "seller_agent"],
                env=seller_environment(mode, seller, settlement_mode),
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
            env=buyer_environment(mode, settlement_mode),
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

        if verifund_enabled(settlement_mode):
            agent = start_child(
                "verifund-agent",
                [sys.executable, "-m", "verifund_agent"],
                env=verifund_agent_environment(settlement_mode),
                url=f"{verifund_agent_url()}/health",
            )
            children.append(agent)
            wait_for_http(
                "verifund-agent",
                f"{verifund_agent_url()}/health",
                timeout=45,
                process=agent.process,
                log_path=agent.log_path,
            )
            registration = subprocess.run(
                [sys.executable, "-m", "verifund_agent.register"],
                cwd=ROOT,
                env=verifund_registration_environment(settlement_mode),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if registration.returncode != 0:
                raise RuntimeError(
                    "Verifund agent registration failed.\n"
                    f"{registration.stdout}{registration.stderr}"
                )

        orchestrator = start_child(
            "orchestrator",
            [sys.executable, "-m", "orchestrator_agent"],
            env=orchestrator_environment(mode, settlement_mode),
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

        _write_pids(children, mode, settlement_mode)
        print("\nMarketMesh is ready")
        print(f"  Console       http://127.0.0.1:{console_port()}")
        print(f"  Orchestrator  {orchestrator_agui_url()}")
        print(f"  Buyer AG-UI   {buyer_agui_url()}")
        print(f"  Registry      {registry_url().rstrip('/')}/v1/sellers")
        if verifund_enabled(settlement_mode):
            print(f"  Verifund      {verifund_url()}")
            print(f"  Verifund A2A  {verifund_agent_url()}")
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
    config.load_env()
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
    parser.add_argument(
        "--verifund",
        choices=["off", "fake", "sandbox"],
        default=None,
        help="start the Verifund control plane and A2A agent in this mode",
    )
    args = parser.parse_args()
    if args.command == "stop":
        return stop_stack()
    return run_stack(args.scripted, args.verifund or verifund_mode())


if __name__ == "__main__":
    raise SystemExit(main())
