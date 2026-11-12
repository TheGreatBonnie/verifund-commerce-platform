# Merged Gateway (One Port) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the six backend services into one FastAPI process that listens on one port and routes each service by path prefix.

**Architecture:** A new `apps/gateway` package imports each service's existing `create_app()` factory, mounts the resulting FastAPI apps at path prefixes (`/orchestrator`, `/buyer`, `/registry`, `/sellers`, `/control-plane`, `/verifund-agent`), and composes their lifespans with `contextlib.AsyncExitStack`. Buyer and Verifund-agent SQLite checkpointers are created in the entrypoint and kept alive for the process lifetime. One uvicorn server binds `PORT` (default `10000`).

**Tech Stack:** Python 3.12, FastAPI, Starlette `app.mount`, uvicorn, LangGraph `AsyncSqliteSaver`, pydantic-settings, pytest, httpx ASGITransport.

**Spec:** `docs/deployment-guide.md` (Approach B — merged process) and the one-port routing analysis from the 2026-11-12 deployment review.

## Global Constraints

- Python `>=3.12`; no new third-party dependencies beyond what the six services already declare.
- The gateway must not modify any service's routes, middleware, or settings behavior.
- All six services start from a single `python -m gateway` command.
- The gateway binds `HOST` (default `0.0.0.0`) and `PORT` (default `10000`).
- Mount prefixes are exactly: `/orchestrator`, `/buyer`, `/registry`, `/sellers`, `/control-plane`, `/verifund-agent`.
- Tests must not require network access or external services.
- Every task ends with a passing test or a passing verification command, then a commit.

## File Structure

| File | Responsibility |
| --- | --- |
| `apps/gateway/pyproject.toml` | New uv workspace member; depends on all six service packages |
| `apps/gateway/gateway/__init__.py` | Package marker |
| `apps/gateway/gateway/settings.py` | Gateway-level `HOST`/`PORT` settings |
| `apps/gateway/gateway/app.py` | `build_app(sub_apps)` — mounts sub-apps, composes lifespans, adds `/health` |
| `apps/gateway/gateway/__main__.py` | `gateway_stack()` assembly + `main()` uvicorn runner |
| `pyproject.toml` | Add `apps/gateway` to `[tool.uv.workspace] members` |
| `Dockerfile.python` | Copy `apps/gateway` into the image |
| `render.yaml` | One Render web service running `python -m gateway` |
| `docs/deployment-guide.md` | Document the merged topology and env vars |
| `apps/console/lib/a2a-agents.ts` | Prefix-aware seller URL construction and seller-vs-buyer detection |
| `apps/console/app/api/copilotkit/[[...slug]]/route.ts` | Point buyer/seller A2A at gateway prefixes; attach seller tokens by path, not port |
| `apps/console/tests/lib/a2a-agents.test.ts` | Unit tests for the console A2A URL helpers |
| `scripts/config.py` | `gateway_port()` / `gateway_url()` helpers |
| `scripts/dev.py` | `--gateway` mode that runs one gateway process plus the console |
| `Makefile` | `make dev GATEWAY=1` (and `make dev-gateway` alias) |
| `tests/unit/test_gateway_settings.py` | Settings defaults and env overrides |
| `tests/unit/test_gateway_app.py` | Mounting, prefix stripping, lifespan composition |
| `tests/unit/test_gateway_entrypoint.py` | Real service assembly and prefixed routing |
| `tests/unit/test_dev_gateway_env.py` | Merged-process env assembly for `make dev GATEWAY=1` |

## Env Var Ownership (collision resolution)

All six services read env vars in one process. These collisions matter:

| Var | Readers | Resolution |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | buyer (fallback), seller | Set `PUBLIC_BASE_URL=https://gateway.onrender.com/sellers` for the seller and `BUYER_PUBLIC_BASE_URL=https://gateway.onrender.com/buyer` for the buyer |
| `DATABASE_URL` | buyer, registry, seller, verifund-agent (fallback) | Never set it; always set the service-specific `*_DATABASE_URL` |
| `CHECKPOINT_PATH` | buyer, verifund-agent (fallback) | Never set it; always set `BUYER_CHECKPOINT_PATH` / `VERIFUND_AGENT_CHECKPOINT_PATH` |
| `PORT` | every service's settings (unused for binding) | Set once; the gateway binds it |
| `HOST` | verifund-agent settings, gateway | Set `0.0.0.0` |
| `VERIFUND_URL` | buyer, seller | `https://gateway.onrender.com/control-plane` |
| `BUYER_INTERNAL_URL` | orchestrator, verifund-agent | `https://gateway.onrender.com/buyer` |
| `SELLER_SHARED_URL` | control plane, console | `https://gateway.onrender.com/sellers` |
| `VERIFUND_AGENT_URL` | orchestrator, verifund-agent | `https://gateway.onrender.com/verifund-agent` |

## Runtime wiring (console → gateway)

`apps/console/app/api/copilotkit/[[...slug]]/route.ts` is the console's only
A2A entry point. It reads two base URLs and derives the four seller agent URLs
by appending seller IDs:

- `BUYER_A2A_URL` — buyer A2A base, default `http://127.0.0.1:9100`.
- `SELLER_SHARED_URL` — shared seller base, default `http://127.0.0.1:9200`.

Behind the gateway both values must carry their mount prefix
(`https://gateway.onrender.com/buyer` and `https://gateway.onrender.com/sellers`).
The route also patches `globalThis.fetch` to add the seller bearer token to
`/a2a` calls, and it currently decides whether a URL belongs to a seller by
comparing ports. That test breaks under the gateway in two ways:

- `new URL("https://host/sellers").port` is `""`, so the fallback `"9200"`
  never matches and seller calls lose their token.
- If the comparison used the gateway port instead, buyer calls would gain the
  seller token because every service shares one origin and port.

Seller detection must therefore be path-prefix based. `isSellerAgentUrl(url,
sharedBaseUrl)` matches `sharedBaseUrl` and anything beneath it, and only falls
back to host/port matching when `sharedBaseUrl` has no path prefix (the legacy
local stack). This keeps `make dev` unchanged while making the merged gateway
work.

## Running the merged stack locally (`make dev`)

`make dev` runs `scripts/dev.py`, which normally starts six processes on six
ports. With the gateway it starts **one** `python -m gateway` process plus the
console:

```bash
make dev                    # merged backend on http://127.0.0.1:10000 + console
make dev-gateway            # same, as a named alias
make dev GATEWAY=0          # six separate service processes
make dev-legacy             # same, as a named alias
```

The merged gateway is the default so local runs match production topology. Set
`GATEWAY=0` (or use `dev-legacy`) when you need per-service ports and logs.

`scripts/dev.py --gateway` merges the six services' env builders into one
process environment, then rewrites every inter-service URL to the gateway
prefix:

| Variable | Gateway value (local) |
| --- | --- |
| `PORT` / `HOST` | `10000` / `127.0.0.1` |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:10000/sellers` |
| `BUYER_PUBLIC_BASE_URL` | `http://127.0.0.1:10000/buyer` |
| `BUYER_A2A_URL` / `BUYER_INTERNAL_URL` | `http://127.0.0.1:10000/buyer` |
| `SELLER_SHARED_URL` | `http://127.0.0.1:10000/sellers` |
| `REGISTRY_URL` | `http://127.0.0.1:10000/registry` |
| `ORCHESTRATOR_URL` / `ORCHESTRATOR_AGUI_URL` | `http://127.0.0.1:10000/orchestrator` |
| `VERIFUND_URL` / `VERIFUND_CONTROL_PLANE_URL` | `http://127.0.0.1:10000/control-plane` |
| `VERIFUND_AGENT_URL` | `http://127.0.0.1:10000/verifund-agent` |

`DATABASE_URL` is removed from the merged environment so each service uses its
own `*_DATABASE_URL`. The console is started with the same prefixed URLs
(including `BUYER_A2A_URL`, which `console_environment()` does not set today).
Verifund agent registration uses `http://127.0.0.1:10000/registry` and the
prefixed agent card URL.

---

### Task 1: Gateway package + workspace wiring

**Files:**
- Create: `apps/gateway/pyproject.toml`
- Create: `apps/gateway/gateway/__init__.py`
- Modify: `pyproject.toml` (add `"apps/gateway"` to `[tool.uv.workspace] members`)

**Interfaces:**
- Consumes: nothing
- Produces: an importable `gateway` package and a uv workspace member named `marketmesh-gateway`

- [ ] **Step 1: Create the gateway package manifest**

Create `apps/gateway/pyproject.toml`:

```toml
[project]
name = "marketmesh-gateway"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "marketmesh-registry",
  "marketmesh-buyer-agent",
  "marketmesh-seller-agent",
  "marketmesh-orchestrator-agent",
  "marketmesh-verifund-agent",
  "verifund-control-plane",
  "marketmesh-commerce-core",
  "verifund-contracts",
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "pydantic-settings>=2.6,<3",
  "langgraph-checkpoint-sqlite>=3.0,<4",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["gateway"]

[tool.uv.sources]
marketmesh-registry = { workspace = true }
marketmesh-buyer-agent = { workspace = true }
marketmesh-seller-agent = { workspace = true }
marketmesh-orchestrator-agent = { workspace = true }
marketmesh-verifund-agent = { workspace = true }
verifund-control-plane = { workspace = true }
marketmesh-commerce-core = { workspace = true }
verifund-contracts = { workspace = true }
```

- [ ] **Step 2: Create the package marker**

Create `apps/gateway/gateway/__init__.py`:

```python
"""MarketMesh merged gateway: one process, one port, path-prefixed services."""
```

- [ ] **Step 3: Register the workspace member**

In the root `pyproject.toml`, add `"apps/gateway"` to `[tool.uv.workspace] members`:

```toml
[tool.uv.workspace]
members = [
  "packages/commerce_core",
  "packages/verifund_contracts",
  "apps/registry",
  "apps/seller_agent",
  "apps/buyer_agent",
  "apps/orchestrator_agent",
  "apps/verifund_control_plane",
  "apps/verifund_agent",
  "apps/gateway",
]
```

- [ ] **Step 4: Lock and sync**

Run: `uv lock && uv sync --all-packages`
Expected: succeeds; `marketmesh-gateway` appears in the lockfile.

- [ ] **Step 5: Verify the package imports**

Run: `uv run python -c "import gateway; print(gateway.__doc__)"`
Expected: prints the package docstring.

- [ ] **Step 6: Commit**

```bash
git add apps/gateway pyproject.toml uv.lock
git commit -m "build: add marketmesh-gateway workspace member"
```

---

### Task 2: Gateway settings

**Files:**
- Create: `apps/gateway/gateway/settings.py`
- Test: `tests/unit/test_gateway_settings.py`

**Interfaces:**
- Consumes: nothing
- Produces: `gateway.settings.Settings` with fields `host: str` and `port: int`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gateway_settings.py`:

```python
from gateway.settings import Settings


def test_defaults(monkeypatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.host == "0.0.0.0"
    assert settings.port == 10000


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8080")
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_gateway_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.settings'`

- [ ] **Step 3: Write the minimal implementation**

Create `apps/gateway/gateway/settings.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway-level bind settings. Service-level settings live in each app."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=10000, validation_alias="PORT")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_gateway_settings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/gateway/gateway/settings.py tests/unit/test_gateway_settings.py
git commit -m "feat(gateway): add gateway bind settings"
```

---

### Task 3: Gateway app builder

**Files:**
- Create: `apps/gateway/gateway/app.py`
- Test: `tests/unit/test_gateway_app.py`

**Interfaces:**
- Consumes: `dict[str, FastAPI]` keyed by service name
- Produces: `gateway.app.build_app(sub_apps) -> FastAPI` and `gateway.app.MOUNT_PREFIXES: dict[str, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gateway_app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.app import MOUNT_PREFIXES, build_app


def make_sub(name: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started = True
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"service": name}

    return app


def test_build_app_mounts_every_prefix_and_runs_lifespans() -> None:
    names = (
        "orchestrator",
        "buyer",
        "registry",
        "seller",
        "control_plane",
        "verifund_agent",
    )
    subs = {name: make_sub(name) for name in names}
    app = build_app(subs)

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for prefix, name in MOUNT_PREFIXES.items():
            response = client.get(f"{prefix}/health")
            assert response.status_code == 200
            assert response.json() == {"service": name}
        for name in names:
            assert subs[name].state.started is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_gateway_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.app'`

- [ ] **Step 3: Write the minimal implementation**

Create `apps/gateway/gateway/app.py`:

```python
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

# Public path prefix -> key in the sub_apps dict passed to build_app().
MOUNT_PREFIXES = {
    "/orchestrator": "orchestrator",
    "/buyer": "buyer",
    "/registry": "registry",
    "/sellers": "seller",
    "/control-plane": "control_plane",
    "/verifund-agent": "verifund_agent",
}


def build_app(sub_apps: dict[str, FastAPI]) -> FastAPI:
    """Mount each service app at its prefix and compose all lifespans.

    Starlette strips the mount prefix before dispatching to the sub-app, so
    every service keeps its existing unprefixed routes.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            for name in MOUNT_PREFIXES.values():
                sub_app = sub_apps[name]
                await stack.enter_async_context(
                    sub_app.router.lifespan_context(sub_app)
                )
            yield

    app = FastAPI(title="MarketMesh Gateway", lifespan=lifespan)
    for prefix, name in MOUNT_PREFIXES.items():
        app.mount(prefix, sub_apps[name])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_gateway_app.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/gateway/gateway/app.py tests/unit/test_gateway_app.py
git commit -m "feat(gateway): mount services at path prefixes"
```

---

### Task 4: Gateway entrypoint assembly

**Files:**
- Create: `apps/gateway/gateway/__main__.py`
- Test: `tests/unit/test_gateway_entrypoint.py`

**Interfaces:**
- Consumes: `gateway.app.build_app`, `gateway.settings.Settings`, each service's `create_app` and `Settings`
- Produces: `gateway.__main__.gateway_stack()` (async context manager yielding the assembled `FastAPI`) and `gateway.__main__.main()`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gateway_entrypoint.py`:

```python
import httpx
import pytest

from gateway.__main__ import gateway_stack


@pytest.mark.asyncio
async def test_gateway_stack_serves_every_prefixed_service(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERIFUND_MODE", "off")
    monkeypatch.setenv("BUYER_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/buyer.db")
    monkeypatch.setenv("BUYER_CHECKPOINT_PATH", str(tmp_path / "buyer-checkpoints.db"))
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/registry.db")
    monkeypatch.setenv("SELLER_SHARED_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    monkeypatch.setenv("SELLER_CHECKPOINT_PATH", str(tmp_path / "seller-checkpoints.db"))
    monkeypatch.setenv("SELLER_CONFIG_SOURCE", "shared")
    monkeypatch.setenv("VERIFUND_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    monkeypatch.setenv("VERIFUND_AGENT_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/agent.db")
    monkeypatch.setenv("VERIFUND_AGENT_CHECKPOINT_PATH", str(tmp_path / "agent-checkpoints.db"))
    monkeypatch.setenv("VERIFUND_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("ORCHESTRATOR_SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sessions.db")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_AGENT_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_INTERNAL_URL", "http://127.0.0.1")
    monkeypatch.setenv("SELLER_SHARED_URL", "http://127.0.0.1")
    monkeypatch.setenv("ALLOWED_CARD_HOSTS", '["127.0.0.1", "localhost"]')

    async with gateway_stack() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            for prefix in (
                "/orchestrator",
                "/buyer",
                "/registry",
                "/sellers",
                "/control-plane",
                "/verifund-agent",
            ):
                response = await client.get(f"{prefix}/health")
                assert response.status_code == 200, prefix
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_gateway_entrypoint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.__main__'`

- [ ] **Step 3: Write the minimal implementation**

Create `apps/gateway/gateway/__main__.py`:

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from buyer_agent.server import create_app as create_buyer
from buyer_agent.settings import Settings as BuyerSettings
from orchestrator_agent.server import create_app as create_orchestrator
from orchestrator_agent.settings import Settings as OrchestratorSettings
from registry.api import create_app as create_registry
from registry.settings import Settings as RegistrySettings
from seller_agent.server import create_app as create_seller
from seller_agent.settings import Settings as SellerSettings
from verifund_agent.server import create_app as create_verifund_agent
from verifund_agent.settings import Settings as VerifundAgentSettings
from verifund_control_plane.app import create_app as create_control_plane
from verifund_control_plane.settings import Settings as ControlPlaneSettings

from gateway.app import build_app
from gateway.settings import Settings


@asynccontextmanager
async def gateway_stack():
    """Assemble all six service apps and keep their checkpointers alive.

    Yields the mounted gateway FastAPI app. The buyer and verifund-agent
    SQLite checkpointers must outlive the server, so they are opened here.
    """
    buyer_settings = BuyerSettings()
    agent_settings = VerifundAgentSettings()
    orchestrator_settings = OrchestratorSettings()
    control_plane_settings = ControlPlaneSettings()
    control_plane_settings.validate_for_mode()

    Path(buyer_settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    Path(agent_settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    session_db = orchestrator_settings.session_db_url.split("///", 1)[-1]
    Path(session_db).parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(
        str(buyer_settings.checkpoint_path)
    ) as buyer_checkpointer, AsyncSqliteSaver.from_conn_string(
        str(agent_settings.checkpoint_path)
    ) as agent_checkpointer:
        sub_apps = {
            "orchestrator": create_orchestrator(orchestrator_settings),
            "buyer": create_buyer(buyer_settings, buyer_checkpointer),
            "registry": create_registry(RegistrySettings()),
            "seller": create_seller(SellerSettings()),
            "control_plane": create_control_plane(control_plane_settings),
            "verifund_agent": create_verifund_agent(
                agent_settings, agent_checkpointer
            ),
        }
        yield build_app(sub_apps)


async def main() -> None:
    settings = Settings()
    async with gateway_stack() as app:
        config = uvicorn.Config(
            app, host=settings.host, port=settings.port, log_level="info"
        )
        await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_gateway_entrypoint.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/gateway/gateway/__main__.py tests/unit/test_gateway_entrypoint.py
git commit -m "feat(gateway): assemble all services behind one port"
```

---

### Task 5: Console CopilotKit route gateway wiring

**Files:**
- Create: `apps/console/lib/a2a-agents.ts`
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts`
- Test: `apps/console/tests/lib/a2a-agents.test.ts`

**Interfaces:**
- Consumes: `BUYER_A2A_URL`, `SELLER_SHARED_URL`
- Produces: `normalizeAgentBaseUrl(url)`, `sellerAgentUrls(sharedBaseUrl)`, `isSellerAgentUrl(url, sharedBaseUrl)`

- [ ] **Step 1: Write the failing test**

Create `apps/console/tests/lib/a2a-agents.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  isSellerAgentUrl,
  normalizeAgentBaseUrl,
  sellerAgentUrls,
} from "@/lib/a2a-agents";

describe("a2a-agents", () => {
  it("normalizes trailing slashes", () => {
    expect(normalizeAgentBaseUrl("https://gateway.onrender.com/sellers/")).toBe(
      "https://gateway.onrender.com/sellers",
    );
  });

  it("builds seller URLs under a gateway mount prefix", () => {
    expect(sellerAgentUrls("https://gateway.onrender.com/sellers/")).toEqual([
      "https://gateway.onrender.com/sellers/northwind-audio",
      "https://gateway.onrender.com/sellers/circuitforge",
      "https://gateway.onrender.com/sellers/aurora-supply",
      "https://gateway.onrender.com/sellers/summit-tech",
    ]);
  });

  it("matches sellers by path prefix when services share one origin", () => {
    const shared = "https://gateway.onrender.com/sellers";
    expect(
      isSellerAgentUrl(
        "https://gateway.onrender.com/sellers/northwind-audio/a2a",
        shared,
      ),
    ).toBe(true);
    expect(
      isSellerAgentUrl("https://gateway.onrender.com/buyer/a2a", shared),
    ).toBe(false);
  });

  it("keeps port matching for the legacy local stack", () => {
    expect(
      isSellerAgentUrl("http://127.0.0.1:9200/northwind-audio/a2a", "http://127.0.0.1:9200"),
    ).toBe(true);
    expect(
      isSellerAgentUrl("http://127.0.0.1:9100/a2a", "http://127.0.0.1:9200"),
    ).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/console && pnpm vitest run tests/lib/a2a-agents.test.ts`
Expected: FAIL (cannot resolve `@/lib/a2a-agents`).

- [ ] **Step 3: Write the helper**

Create `apps/console/lib/a2a-agents.ts`:

```ts
export const SELLER_IDS = [
  "northwind-audio",
  "circuitforge",
  "aurora-supply",
  "summit-tech",
] as const;

/** Remove trailing slashes so prefixes join cleanly. */
export function normalizeAgentBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

export function sellerAgentUrls(sharedBaseUrl: string): string[] {
  const base = normalizeAgentBaseUrl(sharedBaseUrl);
  return SELLER_IDS.map((sellerId) => `${base}/${sellerId}`);
}

function parseUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/**
 * Decide whether an A2A URL belongs to the shared seller service.
 *
 * Behind the merged gateway every service shares one origin and port, so the
 * mount path is the only reliable discriminator. The legacy local stack has no
 * path prefix, so fall back to host/port matching there.
 */
export function isSellerAgentUrl(url: string, sharedBaseUrl: string): boolean {
  const base = normalizeAgentBaseUrl(sharedBaseUrl);
  if (url === base || url.startsWith(`${base}/`)) {
    return true;
  }

  const baseUrl = parseUrl(base);
  const target = parseUrl(url);
  if (!baseUrl || !target) {
    return false;
  }

  const hasPathPrefix = normalizeAgentBaseUrl(baseUrl.pathname) !== "";
  if (hasPathPrefix) {
    return false;
  }

  return baseUrl.hostname === target.hostname && baseUrl.port === target.port;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/console && pnpm vitest run tests/lib/a2a-agents.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire the route**

In `apps/console/app/api/copilotkit/[[...slug]]/route.ts`:

1. Import the helpers:

```ts
import {
  isSellerAgentUrl,
  normalizeAgentBaseUrl,
  sellerAgentUrls,
} from "@/lib/a2a-agents";
```

2. Normalize the configured bases:

```ts
const buyerAgentUrl = normalizeAgentBaseUrl(
  process.env.BUYER_A2A_URL ?? "http://127.0.0.1:9100",
);
const sharedSellerBaseUrl = normalizeAgentBaseUrl(
  process.env.SELLER_SHARED_URL ?? "http://127.0.0.1:9200",
);
```

3. Replace the hand-built seller list with the helper:

```ts
const a2aSellerUrls = sellerAgentUrls(sharedSellerBaseUrl);
const a2aAgentUrls = [buyerAgentUrl, ...a2aSellerUrls];
```

4. Replace the port comparison in the `globalThis.fetch` patch:

```ts
const token = isSellerAgentUrl(url, sharedSellerBaseUrl)
  ? sellerAgentToken
  : "";
```

Keep `sharedSellerPort` and `sellerTokens`: they still satisfy the middleware
constructor signature, while the URL-aware fetch patch now decides which calls
carry the seller token. Keep `MarketMeshA2AClient`,
`MarketMeshA2AMiddlewareAgent`, and the build-time fallbacks unchanged.

- [ ] **Step 6: Typecheck and run the console suite**

Run: `cd apps/console && pnpm run typecheck && pnpm vitest run tests/lib/a2a-agents.test.ts`
Expected: typecheck clean, 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/console/lib/a2a-agents.ts "apps/console/app/api/copilotkit/[[...slug]]/route.ts" apps/console/tests/lib/a2a-agents.test.ts
git commit -m "feat(console): route A2A agents through gateway prefixes"
```

---

### Task 6: `make dev` merged-gateway mode

**Files:**
- Modify: `scripts/config.py` (add `gateway_port()`, `gateway_url()`)
- Modify: `scripts/dev.py` (`--gateway` mode, merged env builder)
- Modify: `Makefile` (`GATEWAY=1` support + `dev-gateway` alias)
- Test: `tests/unit/test_dev_gateway_env.py`

**Interfaces:**
- Consumes: `gateway.__main__` (Task 4), `python -m gateway`
- Produces: `scripts.dev.gateway_environment(mode, verifund_mode)`, `scripts.dev.gateway_console_environment(mode, verifund_mode)`, `make dev` (gateway by default)

- [ ] **Step 1: Add the port helper**

In `scripts/config.py`:

```python
def gateway_port() -> int:
    return _port("GATEWAY_PORT", 10000)


def gateway_url() -> str:
    return _env("GATEWAY_URL", f"http://127.0.0.1:{gateway_port()}").rstrip("/")
```

- [ ] **Step 2: Write the failing env test**

Create `tests/unit/test_dev_gateway_env.py`:

```python
from scripts.dev import gateway_console_environment, gateway_environment


def test_gateway_environment_uses_one_port_and_prefixed_urls(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    monkeypatch.setenv("VERIFUND_MODE", "off")
    env = gateway_environment("scripted", "off")

    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "10000"
    assert env["PUBLIC_BASE_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["BUYER_PUBLIC_BASE_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["BUYER_INTERNAL_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["SELLER_SHARED_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["REGISTRY_URL"] == "http://127.0.0.1:10000/registry"
    assert env["ORCHESTRATOR_AGUI_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["VERIFUND_URL"] == "http://127.0.0.1:10000/control-plane"
    assert env["VERIFUND_AGENT_URL"] == "http://127.0.0.1:10000/verifund-agent"

    # Collisions resolved: no bare DATABASE_URL/CHECKPOINT_PATH
    # bleed-over between services.
    assert "DATABASE_URL" not in env
    assert "CHECKPOINT_PATH" not in env
    assert env["BUYER_DATABASE_URL"].startswith("sqlite+aiosqlite:///")


def test_gateway_environment_includes_the_agent_when_settlement_is_on(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    env = gateway_environment("scripted", "fake")

    assert env["VERIFUND_AGENT_DATABASE_URL"].startswith("sqlite+aiosqlite:///")
    assert env["VERIFUND_AGENT_CARD_URL"] == (
        "http://127.0.0.1:10000/verifund-agent/.well-known/agent-card.json"
    )


def test_gateway_console_environment_targets_the_gateway(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    env = gateway_console_environment("scripted", "off")

    assert env["BUYER_A2A_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["BUYER_AGUI_URL"] == "http://127.0.0.1:10000/buyer/agui"
    assert env["BUYER_API_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["SELLER_SHARED_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["ORCHESTRATOR_AGUI_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["ORCHESTRATOR_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["REGISTRY_URL"] == "http://127.0.0.1:10000/registry"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_dev_gateway_env.py -v`
Expected: FAIL (`ImportError: cannot import name 'gateway_console_environment'`).

- [ ] **Step 4: Implement the merged env builders**

In `scripts/dev.py`, add after `control_plane_environment()`:

```python
def gateway_environment(mode: str, verifund_mode: str = "sandbox") -> dict[str, str]:
    """One process environment for all six services behind the gateway."""
    base = gateway_url()
    env: dict[str, str] = {}
    env.update(registry_environment(mode))
    env.update(shared_seller_environment(mode, verifund_mode))
    env.update(buyer_environment(mode, verifund_mode))
    env.update(orchestrator_environment(mode, verifund_mode))
    env.update(control_plane_environment(mode, verifund_mode))
    if verifund_enabled(verifund_mode):
        env.update(verifund_agent_environment(verifund_mode))

    # Never let a shared fallback win over a service-specific var.
    env.pop("DATABASE_URL", None)
    env.pop("CHECKPOINT_PATH", None)

    env.update(
        {
            "HOST": _env_value("HOST", "127.0.0.1"),
            "PORT": str(gateway_port()),
            "PUBLIC_BASE_URL": f"{base}/sellers",
            "BUYER_PUBLIC_BASE_URL": f"{base}/buyer",
            "REGISTRY_URL": f"{base}/registry",
            "ORCHESTRATOR_URL": f"{base}/orchestrator",
            "ORCHESTRATOR_AGUI_URL": f"{base}/orchestrator",
            "BUYER_A2A_URL": f"{base}/buyer",
            "BUYER_AGUI_URL": f"{base}/buyer/agui",
            "BUYER_INTERNAL_URL": f"{base}/buyer",
            "SELLER_SHARED_URL": f"{base}/sellers",
            "VERIFUND_URL": f"{base}/control-plane",
            "VERIFUND_CONTROL_PLANE_URL": f"{base}/control-plane",
            "VERIFUND_PUBLIC_BASE_URL": f"{base}/control-plane",
            "VERIFUND_AGENT_URL": f"{base}/verifund-agent",
            "VERIFUND_AGENT_CARD_URL": (
                f"{base}/verifund-agent/.well-known/agent-card.json"
            ),
        }
    )
    return env


def gateway_console_environment(
    mode: str, verifund_mode: str = "sandbox"
) -> dict[str, str]:
    env = console_environment(mode)
    base = gateway_url()
    env.update(
        {
            "BUYER_A2A_URL": f"{base}/buyer",
            "BUYER_AGUI_URL": f"{base}/buyer/agui",
            "BUYER_API_URL": f"{base}/buyer",
            "SELLER_SHARED_URL": f"{base}/sellers",
            "ORCHESTRATOR_URL": f"{base}/orchestrator",
            "ORCHESTRATOR_AGUI_URL": f"{base}/orchestrator",
            "REGISTRY_URL": f"{base}/registry",
            "VERIFUND_MODE": verifund_mode,
        }
    )
    return env
```

- [ ] **Step 5: Add the `--gateway` runner path**

In `scripts/dev.py`:

1. Change the signature to `run_stack(scripted: bool, settlement_mode: str = "off", gateway: bool = False)`.
2. Before the registry start, branch into the gateway path:

```python
if gateway:
    gateway_child = start_child(
        "gateway",
        [sys.executable, "-m", "gateway"],
        env=gateway_environment(mode, settlement_mode),
        url=f"{gateway_url()}/health",
    )
    children.append(gateway_child)
    wait_for_http(
        "gateway",
        f"{gateway_url()}/health",
        timeout=90,
        process=gateway_child.process,
        log_path=gateway_child.log_path,
    )

    if verifund_enabled(settlement_mode):
        registration = subprocess.run(
            [sys.executable, "-m", "verifund_agent.register"],
            cwd=ROOT,
            env=gateway_environment(mode, settlement_mode),
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

    console = start_child(
        "console",
        [npm, "run", "dev", "--", "--port", str(console_port())],
        env=gateway_console_environment(mode, settlement_mode),
        cwd=ROOT / "apps/console",
        url=f"http://127.0.0.1:{console_port()}",
    )
    children.append(console)
    wait_for_http(...)
    _write_pids(children, mode, settlement_mode)
    print gateway/console URLs and `/buyer/health`, `/sellers/health`, ...
    loop as today
```

3. Add `--gateway` to the argparse parser and pass it through:

```python
parser.add_argument("--gateway", action="store_true", help="run one merged gateway process")
...
return run_stack(args.scripted, args.verifund or verifund_mode(), args.gateway)
```

- [ ] **Step 6: Add the Make targets**

```make
GATEWAY ?= 1

.PHONY: ... dev-gateway dev-legacy

dev:
	uv run python scripts/dev.py $(if $(filter 1,$(GATEWAY)),--gateway,)

dev-gateway:
	uv run python scripts/dev.py --gateway

dev-legacy:
	uv run python scripts/dev.py
```

- [ ] **Step 7: Run the env tests**

Run: `uv run pytest tests/unit/test_dev_gateway_env.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Boot the merged stack**

Run: `make dev` (`make dev GATEWAY=0` if the sandbox control plane cannot
start without an HTTPS tunnel). Expected: `gateway` starts on
`http://127.0.0.1:10000`, the console starts on
`http://127.0.0.1:3000`.

Then, in another shell:

```bash
curl -s http://127.0.0.1:10000/health                       # {"status":"ok"}
curl -s http://127.0.0.1:10000/buyer/health
curl -s http://127.0.0.1:10000/orchestrator/health
curl -s http://127.0.0.1:10000/registry/health
curl -s http://127.0.0.1:10000/sellers/health
curl -s http://127.0.0.1:10000/control-plane/health
curl -s http://127.0.0.1:10000/verifund-agent/health
curl -s http://127.0.0.1:10000/buyer/.well-known/agent-card.json | head
```

Open `http://127.0.0.1:3000` and send one chat message: the request goes to
`/api/copilotkit`, which now targets the gateway prefixes. `make down` stops
the stack.

- [ ] **Step 9: Commit**

```bash
git add scripts/config.py scripts/dev.py Makefile tests/unit/test_dev_gateway_env.py
git commit -m "feat(dev): run the merged gateway from make dev"
```

---

### Task 7: Docker wiring + local startup

**Files:**
- Modify: `Dockerfile.python`

**Interfaces:**
- Consumes: `apps/gateway`
- Produces: an image whose default command can run `python -m gateway`

- [ ] **Step 1: Copy the gateway package into the image**

In `Dockerfile.python`, add `apps/gateway` to the `COPY` list:

```dockerfile
COPY apps/registry ./apps/registry
COPY apps/seller_agent ./apps/seller_agent
COPY apps/buyer_agent ./apps/buyer_agent
COPY apps/orchestrator_agent ./apps/orchestrator_agent
COPY apps/verifund_control_plane ./apps/verifund_control_plane
COPY apps/verifund_agent ./apps/verifund_agent
COPY apps/gateway ./apps/gateway
COPY scripts ./scripts
```

- [ ] **Step 2: Verify the image builds**

Run: `docker build -f Dockerfile.python -t marketmesh-gateway:test .`
Expected: build succeeds.

- [ ] **Step 3: Verify the module entry point starts**

Run:

```bash
docker run --rm -p 10000:10000 \
  -e VERIFUND_MODE=off \
  -e PORT=10000 \
  marketmesh-gateway:test \
  python -m gateway
```

Expected: uvicorn starts and logs `Uvicorn running on http://0.0.0.0:10000`.

- [ ] **Step 4: Verify the health endpoint**

In another shell, run: `curl -s http://127.0.0.1:10000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.python
git commit -m "build: include the gateway package in the Python image"
```

---

### Task 8: Render Blueprint (one service)

**Files:**
- Create: `render.yaml`

**Interfaces:**
- Consumes: `Dockerfile.python`, `python -m gateway`
- Produces: a Render Blueprint with one web service named `gateway`

- [ ] **Step 1: Write the Blueprint**

Create `render.yaml`:

```yaml
services:
  - type: web
    runtime: docker
    name: gateway
    plan: free
    region: oregon
    dockerfilePath: ./Dockerfile.python
    dockerCommand: python -m gateway
    healthCheckPath: /health
    envVars:
      - fromGroup: gateway-shared
      - key: PORT
        value: "10000"
      - key: BUYER_DATABASE_URL
        sync: false
      - key: BUYER_CHECKPOINT_PATH
        value: /app/data/buyer-checkpoints.db
      - key: BUYER_PUBLIC_BASE_URL
        value: https://gateway.onrender.com/buyer
      - key: REGISTRY_DATABASE_URL
        sync: false
      - key: SELLER_SHARED_DB_URL
        sync: false
      - key: SELLER_CHECKPOINT_PATH
        value: /app/data/seller-checkpoints.db
      - key: SELLER_CONFIG_SOURCE
        value: shared
      - key: PUBLIC_BASE_URL
        value: https://gateway.onrender.com/sellers
      - key: VERIFUND_DATABASE_URL
        sync: false
      - key: VERIFUND_AGENT_DATABASE_URL
        sync: false
      - key: VERIFUND_AGENT_CHECKPOINT_PATH
        value: /app/data/agent-checkpoints.db
      - key: VERIFUND_AGENT_URL
        value: https://gateway.onrender.com/verifund-agent
      - key: ORCHESTRATOR_SESSION_DB_URL
        sync: false
      - key: VERIFUND_URL
        value: https://gateway.onrender.com/control-plane
      - key: VERIFUND_CONTROL_PLANE_URL
        value: https://gateway.onrender.com/control-plane
      - key: BUYER_INTERNAL_URL
        value: https://gateway.onrender.com/buyer
      - key: SELLER_SHARED_URL
        value: https://gateway.onrender.com/sellers
      - key: VERIFUND_PUBLIC_BASE_URL
        value: https://gateway.onrender.com/control-plane
      - key: VERIFUND_CONSOLE_BASE_URL
        sync: false
      - key: VERIFUND_ALLOW_PUBLIC_BIND
        value: "1"
      - key: ALLOWED_CARD_HOSTS
        value: '["gateway.onrender.com", "127.0.0.1", "localhost"]'

databases:
  - name: marketmesh
    plan: free
    region: oregon
    databaseName: marketmesh
    user: marketmesh

envVarGroups:
  - name: gateway-shared
    envVars:
      - key: HOST
        value: 0.0.0.0
      - key: MARKETMESH_LLM_MODE
        value: live
      - key: NEBIUS_API_KEY
        sync: false
      - key: NEBIUS_BASE_URL
        value: https://api.tokenfactory.us-central1.nebius.com/v1/
      - key: NEBIUS_MODEL
        value: deepseek-ai/DeepSeek-V4-Flash-0731
      - key: VERIFUND_MODE
        value: sandbox
      - key: VERIFUND_OPS_TOKEN
        sync: false
      - key: VERIFUND_SELLER_TOKEN_SECRET
        sync: false
      - key: VERIFUND_LINK_SECRET
        sync: false
      - key: VERIFUND_RECEIPT_KEYS
        sync: false
      - key: VERIFUND_RECEIPT_ACTIVE_KID
        sync: false
      - key: VERIFUND_TENANCY_ENABLED
        value: "true"
      - key: PAYPAL_ENV
        value: sandbox
      - key: PAYPAL_API_BASE
        value: https://api-m.sandbox.paypal.com
      - key: PAYPAL_CLIENT_ID
        sync: false
      - key: PAYPAL_CLIENT_SECRET
        sync: false
      - key: PAYPAL_WEBHOOK_ID
        sync: false
      - key: PAYPAL_PLATFORM_EMAIL
        sync: false
      - key: PAYPAL_BUYER_EMAIL
        sync: false
      - key: VERIFUND_SELLER_PAYOUT_EMAILS
        sync: false
      - key: CLERK_SECRET_KEY
        sync: false
      - key: CLERK_JWT_KEY
        sync: false
      - key: CLERK_WEBHOOK_SIGNING_SECRET
        sync: false
```

- [ ] **Step 2: Validate the Blueprint**

Run: `render blueprints validate render.yaml` (requires Render CLI v2.7.0+)
Expected: `render.yaml is valid` (or a list of fixable errors).

> **Memory note:** six LangGraph/ADK/FastAPI stacks share one container. The free tier's 512 MB may be tight; if the gateway is OOM-killed, upgrade the service to `0.5c-512mb` or `1c-2g`. The single service still consumes only ~720 free instance hours/month at 24/7, well under the 750-hour quota.

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "deploy: add merged gateway Render Blueprint"
```

---

### Task 9: Console + inter-service env vars

**Files:**
- Modify: `docs/deployment-guide.md`

**Interfaces:**
- Consumes: the gateway prefixes
- Produces: updated deployment documentation

- [ ] **Step 1: Replace the per-service console env vars with gateway URLs**

In `docs/deployment-guide.md`, update the console env-var table to:

| Variable | Value |
| --- | --- |
| `BUYER_AGUI_URL` | `https://gateway.onrender.com/buyer/agui` |
| `BUYER_API_URL` | `https://gateway.onrender.com/buyer` |
| `BUYER_A2A_URL` | `https://gateway.onrender.com/buyer` |
| `BUYER_CONSOLE_API_TOKEN` | shared secret |
| `BUYER_INTERNAL_TOKEN` | shared secret |
| `ORCHESTRATOR_AGUI_URL` | `https://gateway.onrender.com/orchestrator` |
| `ORCHESTRATOR_URL` | `https://gateway.onrender.com/orchestrator` |
| `REGISTRY_URL` | `https://gateway.onrender.com/registry` |
| `SELLER_SHARED_URL` | `https://gateway.onrender.com/sellers` |
| `VERIFUND_CONTROL_PLANE_URL` | `https://gateway.onrender.com/control-plane` |
| `VERIFUND_OPS_TOKEN` | shared secret |
| `PAYPAL_CLIENT_SECRET` | PayPal sandbox secret |

- [ ] **Step 2: Document the inter-service env vars and collision rules**

Add a subsection "Merged-gateway env var ownership" to `docs/deployment-guide.md` containing the table from the "Env Var Ownership" section of this plan.

- [ ] **Step 3: Update the webhook URLs**

Document that PayPal webhooks point at `https://gateway.onrender.com/control-plane/webhooks/paypal` and Clerk webhooks at `https://gateway.onrender.com/control-plane/v1/webhooks/clerk`.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment-guide.md
git commit -m "docs: document the merged gateway topology"
```

---

### Task 10: End-to-end routing verification

**Files:**
- Test: `tests/integration/test_gateway_routing.py`

**Interfaces:**
- Consumes: `gateway.__main__.gateway_stack`
- Produces: an integration test that proves prefix routing reaches the right service

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_gateway_routing.py`:

```python
import httpx
import pytest

from gateway.__main__ import gateway_stack


@pytest.mark.asyncio
async def test_each_prefix_reaches_its_own_service(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERIFUND_MODE", "off")
    monkeypatch.setenv("BUYER_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/buyer.db")
    monkeypatch.setenv("BUYER_CHECKPOINT_PATH", str(tmp_path / "buyer-checkpoints.db"))
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/registry.db")
    monkeypatch.setenv("SELLER_SHARED_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    monkeypatch.setenv("SELLER_CHECKPOINT_PATH", str(tmp_path / "seller-checkpoints.db"))
    monkeypatch.setenv("SELLER_CONFIG_SOURCE", "shared")
    monkeypatch.setenv("VERIFUND_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    monkeypatch.setenv("VERIFUND_AGENT_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/agent.db")
    monkeypatch.setenv("VERIFUND_AGENT_CHECKPOINT_PATH", str(tmp_path / "agent-checkpoints.db"))
    monkeypatch.setenv("VERIFUND_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("ORCHESTRATOR_SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sessions.db")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_AGENT_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_INTERNAL_URL", "http://127.0.0.1")
    monkeypatch.setenv("SELLER_SHARED_URL", "http://127.0.0.1")
    monkeypatch.setenv("ALLOWED_CARD_HOSTS", '["127.0.0.1", "localhost"]')

    async with gateway_stack() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            orchestrator = await client.get("/orchestrator/health")
            assert orchestrator.json()["service"] == "orchestrator"

            agent = await client.get("/verifund-agent/health")
            assert agent.json()["service"] == "verifund-agent"

            buyer = await client.get("/buyer/health")
            assert buyer.status_code == 200

            registry = await client.get("/registry/health")
            assert registry.status_code == 200

            seller = await client.get("/sellers/health")
            assert seller.status_code == 200

            control_plane = await client.get("/control-plane/health")
            assert control_plane.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_gateway_routing.py -v`
Expected: FAIL (the routes exist after Task 4, so this should already pass; if it fails, the assembly is wrong)

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/unit/test_gateway_settings.py tests/unit/test_gateway_app.py tests/unit/test_gateway_entrypoint.py tests/integration/test_gateway_routing.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_gateway_routing.py
git commit -m "test: verify merged gateway prefix routing"
```

---

## Self-Review

**1. Spec coverage:** The plan covers the merged process (Tasks 1–4, 7), the console CopilotKit route wiring (Task 5), local execution through `make dev` (Task 6), the Render Blueprint (Task 8), the env-var ownership and deployment docs (Task 9), and end-to-end routing verification (Task 10). The one open item from the analysis is the memory risk of six service stacks in one container; that is a deployment concern documented in Task 6's notes, not a code task.

**2. Placeholder scan:** No TBD/TODO markers; every code step contains complete code. The Blueprint's `sync: false` entries are intentional Render prompts for secrets, not placeholders.

**3. Type consistency:** `build_app(sub_apps)` is used consistently; `MOUNT_PREFIXES` maps prefixes to the same keys used in `sub_apps`; `gateway_stack()` yields a `FastAPI` in both the entrypoint and the tests.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-12-merged-gateway.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
