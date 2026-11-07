from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import ServerCallContextBuilder
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

A2A_CALL_PURPOSE = "a2a:call"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    prefix = "bearer "
    if not header.lower().startswith(prefix):
        return ""
    return header[len(prefix):].strip()


class ControlPlaneCredentialVerifier:
    """Verify bearer credentials against the Verifund control plane.

    Only positive results are cached, keyed by token hash. Negative results and
    control-plane errors are never cached, so revocation takes effect as soon as
    a positive entry expires. There is no static-token fallback: if the control
    plane is unreachable the request fails closed.
    """

    def __init__(self, base_url: str, *, ttl_seconds: float = 30.0,
                 timeout_seconds: float = 5.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def verify(self, token: str,
                     purpose: str = A2A_CALL_PURPOSE) -> dict[str, Any] | None:
        if not token:
            return None
        key = token_hash(token)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]

        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/v1/agent-credentials/verify",
                json={"token": token, "purpose": purpose},
            )
        except httpx.HTTPError:
            return None
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("status") != "active":
            return None
        if not data.get("organization_id") or not data.get("agent_id"):
            return None
        self._cache[key] = (now + self.ttl_seconds, data)
        return data

    def clear_cache(self) -> None:
        self._cache.clear()


class StaticDemoCredentialVerifier:
    """Offline verifier backed by a local JSON file.

    The file maps SHA-256 token hashes to caller records. It is only used when
    ``VERIFUND_MODE=off``; it never acts as a fallback for control-plane errors.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    async def verify(self, token: str,
                     purpose: str = A2A_CALL_PURPOSE) -> dict[str, Any] | None:
        if not token:
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        caller = data.get("tokens", {}).get(token_hash(token))
        if not isinstance(caller, dict):
            return None
        if caller.get("status") != "active":
            return None
        if not caller.get("organization_id") or not caller.get("agent_id"):
            return None
        if purpose not in (caller.get("scopes") or []):
            return None
        return caller


class SharedAuthMiddleware(BaseHTTPMiddleware):
    """Require a verified caller credential on A2A paths only."""

    def __init__(self, app, *, verifier) -> None:
        super().__init__(app)
        self.verifier = verifier

    async def dispatch(self, request: Request, call_next):
        if request.url.path.endswith("/a2a") or request.url.path == "/a2a":
            caller = await self.verifier.verify(bearer_token(request))
            if caller is None:
                return JSONResponse(
                    {"error": "unauthorized",
                     "detail": "invalid or missing credential"},
                    status_code=401,
                )
            request.state.caller = caller
        return await call_next(request)


class SharedCallContextBuilder(ServerCallContextBuilder):
    """Copy the path seller and verified caller into the A2A call context."""

    def build(self, request: Request) -> ServerCallContext:
        context = ServerCallContext()
        context.state["seller_id"] = (
            request.path_params.get("seller_id", "") if request.path_params else ""
        )
        context.state["caller"] = getattr(request.state, "caller", None)
        context.state["headers"] = dict(request.headers)
        return context
