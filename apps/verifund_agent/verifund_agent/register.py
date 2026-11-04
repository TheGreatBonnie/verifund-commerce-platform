"""Register the running Verifund A2A agent with the MarketMesh registry."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

import httpx

DEFAULT_REGISTRY_URL = "http://127.0.0.1:9105"
DEFAULT_AGENT_ID = "verifund"


def card_url_from_env() -> str:
    configured = os.environ.get("VERIFUND_AGENT_CARD_URL", "").strip()
    if configured:
        return configured
    base = os.environ.get("VERIFUND_AGENT_URL", "http://127.0.0.1:9301")
    return f"{base.rstrip('/')}/.well-known/agent-card.json"


def registration_payload(agent_id: str, card_url: str) -> dict[str, str]:
    return {"agent_id": agent_id, "card_url": card_url}


async def register(
    *,
    registry_url: str,
    admin_token: str,
    agent_id: str,
    card_url: str,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 1.0,
) -> dict[str, Any]:
    if not admin_token:
        raise RuntimeError("REGISTRY_ADMIN_TOKEN is required")
    deadline = time.monotonic() + timeout_seconds
    last_error = "registry did not accept the agent"
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                response = await client.post(
                    f"{registry_url.rstrip('/')}/v1/agents",
                    headers={"authorization": f"Bearer {admin_token}"},
                    json=registration_payload(agent_id, card_url),
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
            else:
                if response.status_code in {200, 201}:
                    return response.json()
                last_error = (
                    f"registry returned HTTP {response.status_code}: "
                    f"{response.text}"
                )
                if response.status_code in {400, 401, 403, 404}:
                    raise RuntimeError(last_error)
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "agent registration timed out after "
                    f"{timeout_seconds:.0f}s: {last_error}"
                )
            await asyncio.sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register the Verifund A2A agent with the registry."
    )
    parser.add_argument(
        "--registry-url",
        default=os.environ.get("REGISTRY_URL", DEFAULT_REGISTRY_URL),
    )
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("VERIFUND_AGENT_ID", DEFAULT_AGENT_ID),
    )
    parser.add_argument("--card-url", default=card_url_from_env())
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.environ.get("VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS", "60")
        ),
    )
    args = parser.parse_args(argv)
    try:
        row = asyncio.run(
            register(
                registry_url=args.registry_url,
                admin_token=os.environ.get("REGISTRY_ADMIN_TOKEN", ""),
                agent_id=args.agent_id,
                card_url=args.card_url,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except RuntimeError as exc:
        print(
            f"Verifund agent registration failed: {exc}", file=sys.stderr
        )
        return 1
    print(
        f"registered {row.get('agent_id', args.agent_id)} -> "
        f"{row.get('card_url', args.card_url)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

