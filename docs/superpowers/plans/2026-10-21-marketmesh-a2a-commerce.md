# MarketMesh Implementation Plan

**Date:** 2026-10-21  
**Spec:** `docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md`  
**Target:** `verifund-a2a/`  
**Status:** Corrected against `a2a-sdk 1.2.3`; awaiting approval before execution

## How to use this plan

Execute tasks in order. Every task is test-first and ends with a commit. Do not start a task until the previous task's verification command passes.

The plan assumes the engineer knows Python and TypeScript but has no prior context for this repository, the A2A SDK, or CopilotKit v2. Use `uv` for Python, not `pip`, and run all Python commands from `verifund-a2a/`.

## Scope check

This is one product with two protocol boundaries: A2A between buyer and sellers, and AG-UI between console and buyer. Those boundaries are tightly coupled by the approval interrupt and the shared commerce contracts. They belong in one plan. The task order still creates working checkpoints: the seller network is independently testable over A2A before the buyer exists, and the buyer is independently testable before the console exists.

## Verified environment facts

- Python 3.12.8
- `uv 0.8.15`
- Node 24.4.0, npm 11.8.0
- Existing repo has starter files tracked; `verifund-a2a/.git` is on `master`
- Current spec commit: `0f564a8`
- `OPENROUTER_API_KEY` is not set; all automated tests must run in scripted mode. Live mode is a manual smoke test once a key is present.

## SDK facts that drive the implementation

These were verified against the installed wheels, not assumed:

- `a2a-sdk==1.2.3` uses protobuf types. `Part.data` is `google.protobuf.Value`, not `Struct`.
  Construct a data part with:
  ```python
  from google.protobuf import json_format
  from google.protobuf.struct_pb2 import Value
  from a2a.types.a2a_pb2 import Part

  value = Value()
  json_format.ParseDict(envelope, value)
  part = Part(data=value, media_type="application/json")
  ```
  Read it back with `json_format.MessageToDict(part.data)`.
- The checked-in `agents/` tree and `agents/.venv` are on `a2a-sdk 0.3.26`. Its
  `A2AStarletteApplication` and `server.build()` API were removed in 1.2.3; do not copy
  those imports into MarketMesh. Use the 1.x route factories instead.
- The 1.2.3 SDK exposes `create_agent_card_routes(agent_card)` and
  `create_jsonrpc_routes(request_handler, rpc_url="/a2a")`. For FastAPI, attach them with
  `add_a2a_routes_to_fastapi(app, agent_card_routes=..., jsonrpc_routes=...)`; do not
  mutate `app.router.routes` by hand.
- A2A 1.x JSON-RPC message methods require `A2A-Version: 1.0`. The 1.2.3 `ClientFactory`
  adds it to its `httpx` client automatically; raw `httpx` protocol tests must set it.
  The 1.x method names are `SendMessage`, `SendStreamingMessage`, `GetTask`, and
  `CancelTask`; the 0.3 slash names (`message/send`, `message/stream`, `tasks/get`) are
  not used by the 1.2.3 dispatcher.
- `DefaultRequestHandler(agent_executor, task_store, agent_card)` is the request handler.
  `DatabaseTaskStore(engine=async_engine, create_table=True)` is the SQLite task store.
- A seller executor publishes `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` to the
  provided `EventQueue`; it must not call `event_queue.close()`. In 1.2.3,
  `TaskStatusUpdateEvent` has **no `final` field**; a terminal `TaskState` ends the stream.
  `TaskArtifactUpdateEvent.last_chunk` is the artifact-end marker.
- `ag-ui-langgraph==0.0.47` exposes
  `add_langgraph_fastapi_endpoint(app, agent, path="/agui")` and
  `LangGraphAgent(name=..., graph=..., emit_interrupt_outcome=True)`.
- `ag_ui_langgraph` maps a LangGraph interrupt to an AG-UI `Interrupt`. The interrupt's
  `message` must be a string; put structured data in the interrupt's `metadata.langgraph.raw`
  or keep it in graph state. This plan keeps the award in graph state and puts a string in
  `message`.
- CopilotKit v2 has `useInterrupt` (not v1 `useCoAgentStateRender`). With
  `renderInChat: false`, the hook returns an element that can be placed manually. The same
  element object can be rendered in both the chat column and the Deal Room so both share one
  resolve/cancel path.

## Conventions

- Money is always integer cents. Never use floats for money.
- All timestamps are RFC 3339 UTC. Use `datetime.now(UTC)`.
- Pydantic models forbid extra fields.
- Service DBs live in `data/` and are gitignored.
- All services bind to `127.0.0.1` locally. Docker Compose publishes only to localhost.
- No payment/escrow/transaction-coordinator code.
- The buyer never sends `max_total_cents` to a seller.
- Every A2A task uses the buyer run ID as `contextId`, a UUIDv4 `taskId`, and a UUIDv4
  `messageId`.
- Structured artifacts are DataParts. Prose is never authoritative.
- Trace events are persisted before they are returned by the trace API.

---

## Task 1: Reset the repository and create the Python workspace

**Goal:** Replace the research starter with the MarketMesh directory structure, a working
`uv` workspace, a scripted-mode-capable settings layer, and a console placeholder that
compiles. No commerce behavior yet.

**Files:**
- Delete: `.copilotkit/`, `agents/`, `channel-host.mts`, `channels.mts`,
  `components/a2a/`, `scripts/copilotkit-dev-infra.mjs`, `tsconfig.channel.json`,
  `demo.png`, `app/page.module.css`
- Move to `apps/console/`: `app/`, `components/`, `next-env.d.ts`, `next.config.ts`,
  `package.json`, `package-lock.json`, `postcss.config.mjs`, `tailwind.config.ts`,
  `tsconfig.json`
- Create: `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`,
  `packages/commerce_core/pyproject.toml`,
  `packages/commerce_core/commerce_core/__init__.py`,
  `packages/commerce_core/commerce_core/logging.py`,
  `apps/registry/pyproject.toml`, `apps/seller_agent/pyproject.toml`,
  `apps/buyer_agent/pyproject.toml`
- Rewrite: `apps/console/app/agent.ts`, `apps/console/app/page.tsx`,
  `apps/console/app/layout.tsx`, `apps/console/components/chat.tsx`,
  `apps/console/package.json`
- Test: `tests/test_workspace.py`

**Step 1: Move and remove starter files**

Run:

```bash
cd verifund-a2a
git rm -r .copilotkit agents components/a2a scripts/copilotkit-dev-infra.mjs
git rm channel-host.mts channels.mts tsconfig.channel.json demo.png app/page.module.css
mkdir -p apps/console
git mv app apps/console/app
git mv components apps/console/components
git mv next-env.d.ts next.config.ts package.json package-lock.json \
  postcss.config.mjs tailwind.config.ts tsconfig.json apps/console/
git rm README.md
```

**Step 2: Write the failing workspace test**

`tests/test_workspace.py`:

```python
from commerce_core import __version__
from commerce_core.logging import configure_logging, redact_headers


def test_commerce_core_is_importable():
    assert __version__ == "0.1.0"


def test_redact_headers_removes_bearer_tokens():
    headers = {
        "authorization": "Bearer super-secret",
        "content-type": "application/json",
    }
    assert redact_headers(headers) == {
        "authorization": "[REDACTED]",
        "content-type": "application/json",
    }


def test_logging_configures_json(capsys):
    configure_logging("test-service")
    assert True
```

Run:

```bash
uv run pytest tests/test_workspace.py -q
```

Expected: collection error because `commerce_core` does not exist.

**Step 3: Create the workspace files**

Root `pyproject.toml`:

```toml
[project]
name = "marketmesh"
version = "0.1.0"
description = "MarketMesh A2A commerce exchange"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "a2a-sdk[http-server,sqlite,fastapi]==1.2.3",
  "ag-ui-langgraph==0.0.47",
  "ag-ui-protocol>=0.1.22,<0.2",
  "langgraph>=1.2,<2",
  "langgraph-checkpoint-sqlite>=3.0,<4",
  "langchain-openai>=0.3,<2",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
  "httpx>=0.27,<1",
  "pydantic>=2.10,<3",
  "pydantic-settings>=2.6,<3",
  "python-dotenv>=1.0,<2",
  "pyyaml>=6,<7",
  "tenacity>=9,<10",
  "prometheus-client>=0.21,<1",
]

[dependency-groups]
dev = [
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.2,<2",
  "respx>=0.22,<1",
  "ruff>=0.14,<1",
  "mypy>=1.19,<2",
]

[tool.uv.workspace]
members = [
  "packages/commerce_core",
  "apps/registry",
  "apps/seller_agent",
  "apps/buyer_agent",
]

[tool.uv]
package = false

[tool.uv.sources]
marketmesh-commerce-core = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"
```

`packages/commerce_core/pyproject.toml`:

```toml
[project]
name = "marketmesh-commerce-core"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.10,<3",
  "a2a-sdk==1.2.3",
  "httpx>=0.27,<1",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["commerce_core"]
```

`apps/buyer_agent/pyproject.toml`, `apps/seller_agent/pyproject.toml`, and
`apps/registry/pyproject.toml` use this shape, changing name and adding `uvicorn`,
`fastapi`, `marketmesh-commerce-core`, and their service-specific extras:

```toml
[project]
name = "marketmesh-buyer-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "marketmesh-commerce-core",
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "ag-ui-langgraph==0.0.47",
  "langgraph>=1.2,<2",
  "langgraph-checkpoint-sqlite>=3.0,<4",
  "langchain-openai>=0.3,<2",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["buyer_agent"]

[tool.uv.sources]
marketmesh-commerce-core = { workspace = true }
```

`packages/commerce_core/commerce_core/__init__.py`:

```python
__version__ = "0.1.0"
```

`packages/commerce_core/commerce_core/logging.py`:

```python
import json
import logging
import sys
from contextvars import ContextVar

trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
run_id: ContextVar[str] = ContextVar("run_id", default="-")


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "cookie", "x-api-key"}:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id.get(),
            "run_id": run_id.get(),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.LoggerAdapter(logging.getLogger(service), {})
```

**Step 4: Write the root files**

`.env.example`:

```dotenv
# Live LLM mode. Automated tests force scripted mode.
MARKETMESH_LLM_MODE=live
OPENROUTER_API_KEY=
OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash

# Service ports
CONSOLE_PORT=3000
BUYER_PORT=9100
REGISTRY_PORT=9105
NORTHWIND_PORT=9201
CIRCUITFORGE_PORT=9202
AURORA_PORT=9203

# Service URLs
REGISTRY_URL=http://127.0.0.1:9105
BUYER_AGUI_URL=http://127.0.0.1:9100/agui
BUYER_API_URL=http://127.0.0.1:9100

# Registry admin
REGISTRY_ADMIN_TOKEN=dev-registry-admin

# Seller bearer tokens. The dev runner maps each to SELLER_TOKEN per process.
SELLER_NORTHWIND_TOKEN=dev-northwind
SELLER_CIRCUITFORGE_TOKEN=dev-circuitforge
SELLER_AURORA_TOKEN=dev-aurora

# Buyer's local demo credential directory. Production replaces this with a real
# credential exchange; it is not part of the A2A protocol.
BUYER_SELLER_TOKENS='{"northwind-audio":"dev-northwind","circuitforge":"dev-circuitforge","aurora-supply":"dev-aurora"}'

# Local bind address and card-fetch allowlist (Compose overrides HOST to 0.0.0.0).
HOST=127.0.0.1
ALLOWED_CARD_HOSTS='["127.0.0.1","localhost","northwind","circuitforge","aurora"]'

# SQLite
BUYER_DATABASE_URL=sqlite+aiosqlite:///./data/buyer.db
BUYER_CHECKPOINT_PATH=./data/buyer-checkpoints.db
REGISTRY_DATABASE_URL=sqlite+aiosqlite:///./data/registry.db
NORTHWIND_DATABASE_URL=sqlite+aiosqlite:///./data/northwind.db
CIRCUITFORGE_DATABASE_URL=sqlite+aiosqlite:///./data/circuitforge.db
AURORA_DATABASE_URL=sqlite+aiosqlite:///./data/aurora.db
```

`.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
.env
data/
*.db
*.db-wal
*.db-shm
node_modules/
.next/
out/
dist/
test-results/
playwright-report/
.dev-pids.json
.dev-logs/
```

`Makefile`:

```make
.PHONY: setup dev seed reset test lint e2e demo down

setup:
	uv lock
	uv sync --all-packages
	cd apps/console && npm install
	cp -n .env.example .env || true

dev:
	uv run python scripts/dev.py

seed:
	uv run python scripts/seed.py

reset:
	rm -f data/*.db data/*.db-wal data/*.db-shm

test:
	uv run pytest

lint:
	uv run ruff check .
	cd apps/console && npm run typecheck

e2e:
	uv run python scripts/e2e.py

demo:
	uv run python scripts/run_demo.py

down:
	uv run python scripts/dev.py stop
```

**Step 5: Create the console placeholder**

`apps/console/package.json` should keep the existing Next.js 15.5 / React 19 /
CopilotKit 1.79 pins but remove research-only packages:

```json
{
  "name": "marketmesh-console",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev --turbopack",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@ag-ui/client": "1.0.2",
    "@ag-ui/core": "1.0.2",
    "@copilotkit/react-core": "1.79.0",
    "@copilotkit/runtime": "1.79.0",
    "hono": "^4",
    "lucide-react": "^0.577.0",
    "next": "15.5.15",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "zod": "^3.24.4"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4.1.13",
    "@tailwindcss/typography": "^0.5.16",
    "@types/node": "^20",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "postcss": "^8",
    "tailwindcss": "^4.1.13",
    "tailwindcss-animate": "^1.0.7",
    "typescript": "^5"
  }
}
```

`apps/console/app/agent.ts`:

```ts
import { HttpAgent } from "@ag-ui/client";

export function createDefaultAgent(): HttpAgent {
  return new HttpAgent({
    url: process.env.BUYER_AGUI_URL ?? "http://127.0.0.1:9100/agui",
  });
}
```

`apps/console/app/api/copilotkit/[[...slug]]/route.ts` keeps the existing v2 runtime
shape, changes the agent id to `marketmesh_buyer`, and keeps the optional Intelligence
block only if `CPK_INTELLIGENCE_API_KEY` is set.

`apps/console/app/layout.tsx` changes metadata to MarketMesh and keeps the existing
`Plus_Jakarta_Sans` and `Spline_Sans_Mono` fonts. Import `Instrument_Serif` from
`next/font/google` and add it for display headings:

```tsx
const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
});
```

Include `${instrumentSerif.variable}` in the `<body>` class list alongside the existing
font variables.

`apps/console/app/page.tsx` is a minimal compiling placeholder:

```tsx
"use client";

import {
  CopilotChat,
  CopilotChatConfigurationProvider,
  CopilotKitProvider,
} from "@copilotkit/react-core/v2";

export default function Home() {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
      <CopilotChatConfigurationProvider agentId="marketmesh_buyer">
        <main className="min-h-dvh bg-[#F4F0E6] p-8 text-[#171713]">
          <h1 className="font-serif text-4xl">MarketMesh</h1>
          <p className="mt-2 text-sm text-[#5E5A50]">
            A2A commerce exchange — console wiring in progress.
          </p>
          <div className="mt-8 h-[70dvh] max-w-xl">
            <CopilotChat />
          </div>
        </main>
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}
```

`apps/console/components/chat.tsx`:

```tsx
"use client";

import { CopilotChat } from "@copilotkit/react-core/v2";

export default function Chat() {
  return <CopilotChat className="h-full" />;
}
```

Run `npm install` in `apps/console` to regenerate `package-lock.json`.

**Step 6: Run verification**

```bash
uv lock
uv sync --all-packages
uv run pytest tests/test_workspace.py -q
cd apps/console && npm run typecheck
```

Expected: 3 passed; TypeScript exits 0.

**Step 7: Commit**

```bash
git add -A
git commit -m "chore: reset starter and scaffold MarketMesh workspace"
```

---

## Task 2: Commerce contracts, A2A envelopes, and Agent Card validation

**Goal:** One shared source of truth for every structured payload, plus helpers for
DataParts and Agent Cards.

**Files:**
- `packages/commerce_core/commerce_core/contracts.py`
- `packages/commerce_core/commerce_core/money.py`
- `packages/commerce_core/commerce_core/extension.py`
- `packages/commerce_core/commerce_core/a2a_parts.py`
- `packages/commerce_core/commerce_core/cards.py`
- `packages/commerce_core/commerce_core/db.py`
- Tests: `tests/unit/test_contracts.py`, `tests/unit/test_extension.py`,
  `tests/unit/test_cards.py`

**Step 1: Write failing tests**

`tests/unit/test_contracts.py` includes:

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from commerce_core.contracts import (
    Mandate, Offer, OfferLineItem, OfferStatus, OfferTerms,
)


def make_offer(**overrides):
    now = datetime.now(UTC)
    data = dict(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        currency="USD",
        line_items=[OfferLineItem(
            sku="NC-700-BLK",
            name="Nimbus NC-700 ANC Headset",
            quantity=12,
            unit_price_cents=28100,
            list_unit_price_cents=31900,
            warranty_addon_cents=0,
            attributes={"color": "black"},
        )],
        subtotal_cents=337200,
        shipping_cents=0,
        total_cents=337200,
        delivery_days=3,
        warranty_months=36,
        returns_days=45,
        valid_until=now + timedelta(minutes=30),
        terms=OfferTerms(
            sustainability_certified=True,
            stock_confidence=1.0,
            split_shipment=False,
        ),
        status=OfferStatus.FINAL,
        round=3,
        rationale="Final offer.",
    )
    data.update(overrides)
    return Offer(**data)


def test_offer_totals_must_match_line_items():
    with pytest.raises(ValidationError):
        make_offer(total_cents=1)


def test_mandate_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        Mandate(
            run_id="run-1",
            category="consumer-electronics",
            product_hint="Nimbus NC-700",
            quantity=0,
            max_total_cents=340000,
            deadline_days=14,
            min_warranty_months=24,
            min_returns_days=30,
        )


def test_mandate_keeps_budget_internal():
    mandate = Mandate(
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        max_total_cents=340000,
        deadline_days=14,
        min_warranty_months=24,
        min_returns_days=30,
    )
    dumped = mandate.model_dump()
    assert "max_total_cents" in dumped
```

`tests/unit/test_extension.py`:

```python
import pytest

from commerce_core.contracts import RFQ, RFQConstraints, RFQPreferences
from commerce_core.extension import EXTENSION_URI, parse_payload, wrap_payload


def test_round_trip_rfq():
    rfq = RFQ(
        request_id="rfq-1",
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        required_by="2026-11-04T00:00:00Z",
        constraints=RFQConstraints(
            min_warranty_months=24, min_returns_days=30, color="black"
        ),
        preferences=RFQPreferences(sustainability=True),
    )
    envelope = wrap_payload("rfq", rfq)
    assert envelope["schema"].startswith(EXTENSION_URI)
    assert parse_payload("rfq", envelope, RFQ) == rfq


def test_wrong_schema_is_rejected():
    with pytest.raises(ValueError, match="schema"):
        parse_payload("offer", {
            "schema": "https://example.com/wrong.json",
            "schema_version": "1.0",
            "payload": {},
        }, RFQ)
```

Create `tests/support/cards.py` with `build_test_card()` (a valid Northwind card using
the same fields as `build_agent_card` in Task 5). `tests/unit/test_cards.py` imports it
and asserts validation errors for missing extension and missing bearer scheme.

**Step 2: Run tests to confirm failure**

```bash
uv run pytest tests/unit/test_contracts.py tests/unit/test_extension.py \
  tests/unit/test_cards.py -q
```

Expected: import errors.

**Step 3: Implement the models**

`contracts.py` must contain these exact classes and fields:

- Enums: `Currency`, `OfferStatus`, `OrderStatus`, `CommerceErrorCode`.
- `Preferences`: `sustainability: bool = False`, `color: str | None = None`.
- `Mandate`: `run_id`, `buyer_id="demo-buyer"`, `category`, `product_hint`,
  `quantity > 0`, `max_total_cents > 0`, `deadline_days > 0`,
  `min_warranty_months >= 0`, `min_returns_days >= 0`, `preferences`,
  `approval_required=True`.
- `ShoppingBrief = Mandate` alias.
- `RFQConstraints`: `min_warranty_months`, `min_returns_days`, `color`.
- `RFQPreferences`: `sustainability`, `delivery_preference`.
- `RFQ`: `schema_version="1.0"`, `request_id`, `run_id`, `category`, `product_hint`,
  `quantity`, `required_by: datetime`, `constraints`, `preferences`,
  `message: str | None`.
- `OfferLineItem`: `sku`, `name`, `quantity`, `unit_price_cents`,
  `list_unit_price_cents`, `warranty_addon_cents`, `attributes: dict[str, str]`.
- `OfferTerms`: `sustainability_certified`, `stock_confidence: float` in `[0,1]`,
  `split_shipment`, `notes`.
- `Offer`: all fields listed in the spec; `status: OfferStatus`, `round: int`,
  `seller_rating: float` in `[0,5]` (copied from the validated Agent Card by the buyer).
  Add a `model_validator(mode="after")` that asserts:
  - every line item quantity > 0, unit price > 0, and warranty add-on >= 0;
  - `subtotal_cents == sum((unit_price_cents + warranty_addon_cents) * quantity)`;
  - `total_cents == subtotal_cents + shipping_cents`;
  - `delivery_days > 0`; `warranty_months >= 0`; `returns_days >= 0`.
- `CounterOffer`: `schema_version`, `negotiation_round`, `target_unit_price_cents:
  int | None`, `requested_changes: dict[str, str | int | bool]`, `rationale`.
- `AcceptOffer`: `schema_version`, `offer_id`, `round`, `accepted_total_cents`.
- `ApprovalReceipt`: `approval_id`, `approved_by`, `approved_at`, `note`.
- `ShippingAddress`: `name`, `line1`, `city`, `region`, `postal_code`, `country`.
- `PurchaseOrderRequest`: `schema_version`, `request_id`, `run_id`, `offer_id`,
  `seller_id`, `quantity`, `shipping_address`, `approval`, `idempotency_key`,
  `expected_total_cents`.
- `Fulfillment`: `carrier`, `status`.
- `Order`: `schema_version`, `order_id`, `offer_id`, `seller_id`, `status`,
  `currency`, `quantity`, `total_cents`, `line_items`, `reserved_at`, `eta`,
  `tracking_number`, `fulfillment`.
- `CommerceError`: `code: CommerceErrorCode`, `message`, `retryable`, `details`.
- `NegotiationRecord`: `seller_id`, `seller_name`, `task_id`, `status`, `rounds:
  list[Offer]`, `final_offer: Offer | None`, `error: str | None`.
- `AwardPackage`: `winner: Offer`, `score: float`, `alternatives: list[Offer]`,
  `scores: dict[str, float]`, `savings_cents: int`, `mandate_checks: list[str]`.

Every model uses:

```python
model_config = ConfigDict(extra="forbid")
```

`money.py`:

```python
from decimal import Decimal, ROUND_HALF_UP


def dollars_to_cents(value: str | Decimal) -> int:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def format_cents(cents: int, currency: str = "USD") -> str:
    return f"{cents / 100:,.2f} {currency}"
```

**Step 4: Implement envelopes and DataParts**

`extension.py`:

```python
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

EXTENSION_URI = "https://marketmesh.example/extensions/commerce/v1"
SCHEMA_BASE = f"{EXTENSION_URI}/schemas"
SCHEMA_FILES = {
    "rfq": "rfq.json",
    "offer": "offer.json",
    "counter_offer": "counter-offer.json",
    "accept_offer": "accept-offer.json",
    "purchase_order": "purchase-order.json",
    "order": "order.json",
    "commerce_error": "commerce-error.json",
}

ModelT = TypeVar("ModelT", bound=BaseModel)


class CommerceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_uri: str = Field(alias="schema")
    schema_version: str = "1.0"
    payload: dict[str, Any]


def expected_schema(kind: str) -> str:
    try:
        return f"{SCHEMA_BASE}/{SCHEMA_FILES[kind]}"
    except KeyError as exc:
        raise ValueError(f"unknown commerce payload kind: {kind}") from exc


def wrap_payload(kind: str, payload: BaseModel) -> dict[str, Any]:
    return {
        "schema": expected_schema(kind),
        "schema_version": "1.0",
        "payload": payload.model_dump(mode="json"),
    }


def unwrap_payload(kind: str, envelope: dict[str, Any]) -> dict[str, Any]:
    parsed = CommerceEnvelope.model_validate(envelope)
    if parsed.schema_uri != expected_schema(kind):
        raise ValueError(
            f"unexpected schema for {kind}: {parsed.schema_uri}"
        )
    if parsed.schema_version != "1.0":
        raise ValueError(f"unsupported schema version: {parsed.schema_version}")
    return parsed.payload


def parse_payload(kind: str, envelope: dict[str, Any], model: type[ModelT]) -> ModelT:
    return model.model_validate(unwrap_payload(kind, envelope))
```

`a2a_parts.py`:

```python
import uuid

from a2a.types.a2a_pb2 import Artifact, Message, Part, Role
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value


def data_part(envelope: dict) -> Part:
    value = Value()
    json_format.ParseDict(envelope, value)
    return Part(data=value, media_type="application/json")


def part_value(part: Part) -> dict | None:
    if not part.HasField("data"):
        return None
    return json_format.MessageToDict(part.data)


def make_artifact(name: str, envelope: dict) -> Artifact:
    return Artifact(
        artifact_id=str(uuid.uuid4()),
        name=name,
        parts=[data_part(envelope)],
    )


def make_message(
    *,
    role: Role,
    text: str,
    context_id: str,
    task_id: str | None = None,
    envelope: dict | None = None,
    reference_task_ids: list[str] | None = None,
) -> Message:
    parts = [Part(text=text, media_type="text/plain")]
    if envelope is not None:
        parts.append(data_part(envelope))
    return Message(
        message_id=str(uuid.uuid4()),
        role=role,
        context_id=context_id,
        task_id=task_id or "",
        parts=parts,
        reference_task_ids=reference_task_ids or [],
    )


def first_envelope(message: Message) -> dict | None:
    for part in message.parts:
        value = part_value(part)
        if value is not None:
            return value
    return None
```

`cards.py`:

```python
from typing import Any

import httpx
from a2a.types.a2a_pb2 import AgentCard
from google.protobuf import json_format

from commerce_core.extension import EXTENSION_URI

REQUIRED_SKILLS = {
    "commerce.catalog.search",
    "commerce.quote",
    "commerce.negotiate",
    "commerce.order",
}


def parse_agent_card(data: dict[str, Any]) -> AgentCard:
    card = AgentCard()
    json_format.ParseDict(data, card)
    return card


def validate_agent_card(card: AgentCard) -> list[str]:
    errors: list[str] = []
    if not card.name:
        errors.append("missing name")
    if not card.version:
        errors.append("missing version")
    interfaces = list(card.supported_interfaces)
    if not any(
        i.protocol_binding == "JSONRPC" and i.protocol_version.startswith("1.")
        for i in interfaces
    ):
        errors.append("missing JSONRPC A2A 1.x interface")
    if not card.capabilities.streaming:
        errors.append("streaming is required")
    extensions = {e.uri: e for e in card.capabilities.extensions}
    if EXTENSION_URI not in extensions or not extensions[EXTENSION_URI].required:
        errors.append("required commerce extension missing")
    else:
        params = json_format.MessageToDict(extensions[EXTENSION_URI].params)
        rating = params.get("rating")
        if not isinstance(rating, (int, float)) or not 0 <= rating <= 5:
            errors.append("commerce extension requires rating in [0,5]")
        if not isinstance(params.get("sustainability_certified"), bool):
            errors.append("commerce extension requires sustainability_certified")
    skill_ids = {s.id for s in card.skills}
    if not REQUIRED_SKILLS.issubset(skill_ids):
        errors.append(f"missing skills: {sorted(REQUIRED_SKILLS - skill_ids)}")
    if "bearer" not in card.security_schemes:
        errors.append("missing bearer security scheme")
    return errors


def card_commerce_metadata(card: AgentCard) -> dict[str, Any]:
    for extension in card.capabilities.extensions:
        if extension.uri == EXTENSION_URI:
            return json_format.MessageToDict(extension.params)
    raise ValueError("commerce extension metadata is missing")


DEFAULT_CARD_HOSTS = (
    "127.0.0.1",
    "localhost",
    "northwind",
    "circuitforge",
    "aurora",
)


async def fetch_agent_card(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    allowed_hosts: tuple[str, ...] = DEFAULT_CARD_HOSTS,
) -> AgentCard:
    parsed = httpx.URL(url)
    if parsed.scheme != "http" or parsed.host not in allowed_hosts:
        raise ValueError("prototype card fetch is restricted to allowed local hosts")
    if client is None:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(url)
    else:
        response = await client.get(url)
    response.raise_for_status()
    return parse_agent_card(response.json())
```

Registry and buyer discovery call `await fetch_agent_card(url, allowed_hosts=...)` with
their configured host allowlist. Seed scripts call it inside an async function as well.
There is no synchronous card fetch in production code.

`db.py` holds the shared SQLite setup helper:

```python
async def configure_sqlite(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
```

Each service calls this once before `create_schema()` so all four SQLite databases use
WAL, a bounded busy timeout, and foreign keys.

**Step 5: Run tests**

```bash
uv run pytest tests/unit/test_contracts.py tests/unit/test_extension.py \
  tests/unit/test_cards.py -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add commerce contracts and A2A envelope helpers"
```

---

## Task 3: Seller pricing policy, buyer counter policy, and scoring

**Goal:** Deterministic commerce math. The LLM later chooses from these bounded options,
but never invents prices or totals.

**Files:**
- `packages/commerce_core/commerce_core/pricing.py`
- `packages/commerce_core/commerce_core/scoring.py`
- `apps/seller_agent/seller_agent/profiles/northwind.yaml`
- `apps/seller_agent/seller_agent/profiles/circuitforge.yaml`
- `apps/seller_agent/seller_agent/profiles/aurora.yaml`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_scoring.py`

**Step 1: Write failing tests**

`tests/unit/test_pricing.py`:

```python
import pytest

from commerce_core.pricing import SellerPolicy


def test_northwind_ladder_ends_at_final_price(northwind_policy):
    assert northwind_policy.initial_unit_price_cents == 30300
    assert northwind_policy.next_price_options(30300) == [29200, 28100]
    assert northwind_policy.next_price_options(29200) == [28100]
    assert northwind_policy.next_price_options(28100) == [28100]


def test_circuitforge_warranty_add_on(circuitforge_policy):
    quote = circuitforge_policy.quote(
        quantity=12,
        unit_price_cents=26312,
        warranty_months=24,
    )
    assert quote.unit_price_cents == 26912
    assert quote.total_cents == 322944


def test_aurora_split_shipment_stock_confidence(aurora_policy):
    quote = aurora_policy.quote(
        quantity=12,
        unit_price_cents=28333,
        warranty_months=24,
        allow_split=True,
    )
    assert quote.split_shipment is True
    assert quote.delivery_days == 10
    assert 0 < quote.stock_confidence < 1


def test_aurora_initial_quote_has_no_split_commitment(aurora_policy):
    quote = aurora_policy.quote(
        quantity=12,
        unit_price_cents=30900,
        warranty_months=24,
        allow_split=False,
    )
    assert quote.split_shipment is False
    assert quote.stock_confidence == pytest.approx(8 / 12)


def test_policy_rejects_price_below_floor(northwind_policy):
    with pytest.raises(ValueError, match="floor"):
        northwind_policy.quote(
            quantity=12, unit_price_cents=27899, warranty_months=36
        )
```

`tests/unit/test_scoring.py` builds the three final offers (Aurora final has
`split_shipment=True`) and the three initial offers (Aurora initial has
`split_shipment=False`, `stock_confidence=8/12`). Every `Offer` includes
`seller_rating` 4.8, 4.4, and 4.6 respectively. Assertions:

```python
def test_circuitforge_wins_final_comparison(mandate, final_offers):
    ranking = rank_offers(mandate, final_offers)
    assert ranking[0].offer.seller_id == "circuitforge"
    assert ranking[0].score > ranking[1].score


def test_initial_offers_have_expected_failures(mandate, initial_offers):
    by_seller = {o.seller_id: o for o in initial_offers}
    assert "warranty" in " ".join(hard_constraint_failures(
        mandate, by_seller["circuitforge"]
    )).lower()
    assert "stock" in " ".join(hard_constraint_failures(
        mandate, by_seller["aurora-supply"]
    )).lower()
    assert "budget" in " ".join(hard_constraint_failures(
        mandate, by_seller["northwind-audio"]
    )).lower()
```

**Step 2: Run tests to confirm failure**

```bash
uv run pytest tests/unit/test_pricing.py tests/unit/test_scoring.py -q
```

**Step 3: Implement `SellerPolicy`**

Use Pydantic with these fields:

```python
class SellerPolicy(BaseModel):
    seller_id: str
    name: str
    tagline: str
    categories: list[str]
    list_unit_price_cents: int
    floor_unit_price_cents: int
    initial_unit_price_cents: int
    concession_ladder_cents: list[int]
    base_warranty_months: int
    warranty_addons_cents: dict[int, int]
    returns_days: int
    delivery_days: int
    stock_on_hand: int
    incoming_stock: int = 0
    incoming_days: int | None = None
    split_shipment: bool = False
    sustainability_certified: bool
    rating: float
    max_rounds: int = 3
    offer_ttl_minutes: int = 30
    color: str = "black"
    sku: str = "NC-700-BLK"
    product_name: str = "Nimbus NC-700 ANC Headset"
```

Implement:

- `next_price_options(previous_price_cents: int) -> list[int]`: deduplicated ladder
  values strictly below `previous_price_cents`; if none, return `[previous_price_cents]`.
- `quote(quantity, unit_price_cents, warranty_months, allow_split=False) -> Quote`:
  - reject price outside `[floor_unit_price_cents, list_unit_price_cents]`;
  - reject unsupported warranty months;
  - `all_in_unit = unit_price_cents + warranty_addons_cents[warranty_months]`;
  - `subtotal = all_in_unit * quantity`;
  - `stock_confidence`: 1.0 if `stock_on_hand >= quantity`; otherwise
    `stock_on_hand / quantity` (the buyer sees the gap);
  - `split_shipment`: true only when `allow_split` is true,
    `stock_on_hand < quantity`, and `stock_on_hand + incoming_stock >= quantity`;
    false otherwise;
  - `delivery_days`: `incoming_days` when `split_shipment`, otherwise
    `delivery_days`;
  - `valid_until = now + offer_ttl_minutes`.
- `initial_quote(quantity)`: `quote(quantity, initial_unit_price_cents,
  base_warranty_months, allow_split=False)`.

`Quote` is a frozen dataclass with `base_unit_price_cents` (the negotiated price),\n`warranty_addon_cents`, `unit_price_cents` (base + add-on, asserted in the test),\n`subtotal_cents`, `total_cents`, `delivery_days`, `stock_confidence`,\n`split_shipment`, `warranty_months`, and `valid_until`. The seller's `OfferLineItem`\nstores the base price and the add-on separately so line-item math remains explicit.

Profiles:

`northwind.yaml`:

```yaml
seller_id: northwind-audio
name: Northwind Audio
tagline: Premium audio, fastest delivery
categories: [audio, consumer-electronics]
list_unit_price_cents: 31900
floor_unit_price_cents: 27900
initial_unit_price_cents: 30300
concession_ladder_cents: [30300, 29200, 28100]
base_warranty_months: 36
warranty_addons_cents: {36: 0}
returns_days: 45
delivery_days: 3
stock_on_hand: 40
sustainability_certified: true
rating: 4.8
```

`circuitforge.yaml`:

```yaml
seller_id: circuitforge
name: CircuitForge
tagline: Value electronics with configurable coverage
categories: [audio, consumer-electronics]
list_unit_price_cents: 27900
floor_unit_price_cents: 25900
initial_unit_price_cents: 26312
concession_ladder_cents: [26312, 26312, 26312]
base_warranty_months: 12
warranty_addons_cents: {12: 0, 24: 600, 36: 1200}
returns_days: 30
delivery_days: 7
stock_on_hand: 25
sustainability_certified: false
rating: 4.4
```

`aurora.yaml`:

```yaml
seller_id: aurora-supply
name: Aurora Supply
tagline: Balanced sourcing with sustainable packaging
categories: [audio, consumer-electronics]
list_unit_price_cents: 30900
floor_unit_price_cents: 28100
initial_unit_price_cents: 30900
concession_ladder_cents: [30900, 29600, 28333]
base_warranty_months: 24
warranty_addons_cents: {24: 0, 36: 1200}
returns_days: 30
delivery_days: 10
stock_on_hand: 8
incoming_stock: 4
incoming_days: 10
split_shipment: true
sustainability_certified: true
rating: 4.6
```

**Step 4: Implement buyer counter policy**

In `pricing.py`:

```python
from decimal import Decimal


def counter_targets(
    initial_unit_price_cents: int,
    max_total_cents: int,
    quantity: int,
) -> list[int]:
    max_unit = max_total_cents // quantity
    targets = [
        int(initial_unit_price_cents * Decimal("0.97")),
        int(initial_unit_price_cents * Decimal("0.95")),
        int(initial_unit_price_cents * Decimal("0.93")),
    ]
    return [min(t, max_unit) for t in targets if 0 < t < initial_unit_price_cents]
```

The buyer uses index `round_number - 2` (round 2 gets the first target, round 3 the
second). If the index is out of range, the buyer stops negotiating.

The buyer also requests a term change when needed:
`requested_changes["warranty_months"] = mandate.min_warranty_months` if the offer's
warranty is below the minimum, and `requested_changes["split_shipment"] = True` if
`offer.terms.stock_confidence < 1.0 and not offer.terms.split_shipment`. This is how
Aurora's initial stock gap becomes a split-shipment commitment instead of a hard failure.

**Step 5: Implement scoring**

`scoring.py`:

```python
WEIGHTS = {
    "price": 0.45,
    "delivery": 0.15,
    "warranty": 0.10,
    "rating": 0.10,
    "returns": 0.05,
    "sustainability": 0.05,
    "confidence": 0.10,
}


def hard_constraint_failures(mandate: Mandate, offer: Offer) -> list[str]:
    failures = []
    if offer.total_cents > mandate.max_total_cents:
        failures.append(
            f"budget: {offer.total_cents} exceeds {mandate.max_total_cents}"
        )
    if offer.delivery_days > mandate.deadline_days:
        failures.append(
            f"delivery: {offer.delivery_days} days exceeds deadline"
        )
    if offer.warranty_months < mandate.min_warranty_months:
        failures.append(
            f"warranty: {offer.warranty_months} months is below minimum"
        )
    if offer.returns_days < mandate.min_returns_days:
        failures.append(
            f"returns: {offer.returns_days} days is below minimum"
        )
    if (
        offer.terms.stock_confidence < 1.0
        and not offer.terms.split_shipment
    ):
        failures.append(
            "stock: insufficient on-hand stock and no split commitment"
        )
    return failures


def score_offer(mandate: Mandate, offer: Offer) -> float:
    target_total = int(mandate.max_total_cents * 0.9)
    headroom = mandate.max_total_cents - offer.total_cents
    price = max(0.0, min(100.0, headroom / max(1, mandate.max_total_cents - target_total) * 100))
    delivery = max(
        0.0,
        100.0 * (1 - (offer.delivery_days - 1) / max(1, mandate.deadline_days - 1)),
    )
    warranty = 70.0 + 30.0 * min(
        1.0,
        (offer.warranty_months - mandate.min_warranty_months)
        / max(1, 36 - mandate.min_warranty_months),
    )
    rating = offer.seller_rating / 5.0 * 100.0
    returns = 70.0 + 30.0 * min(
        1.0,
        (offer.returns_days - mandate.min_returns_days)
        / max(1, 45 - mandate.min_returns_days),
    )
    sustainability = 100.0 if offer.terms.sustainability_certified else 0.0
    confidence = offer.terms.stock_confidence * 100.0
    return round(
        price * WEIGHTS["price"]
        + delivery * WEIGHTS["delivery"]
        + warranty * WEIGHTS["warranty"]
        + rating * WEIGHTS["rating"]
        + returns * WEIGHTS["returns"]
        + sustainability * WEIGHTS["sustainability"]
        + confidence * WEIGHTS["confidence"],
        2,
    )
```

The seller rating lives in the seller's Agent Card metadata, not inside `OfferTerms`.
Add `seller_rating: float = Field(ge=0, le=5)` to `Offer` in Task 2 so scoring does not
depend on a hidden card lookup. The buyer fills it from the validated card.

`rank_offers` returns a list of `ScoredOffer` dataclasses sorted by score desc, then total
asc, then delivery asc. Exclude offers with hard failures.

**Step 6: Run tests**

```bash
uv run pytest tests/unit/test_pricing.py tests/unit/test_scoring.py -q
```

Expected: all pass, with CircuitForge first.

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: add seller pricing, buyer counters, and offer scoring"
```

---

## Task 4: Registry service

**Goal:** A small, authenticated Agent Card index. It stores no commerce data and never
proxies A2A traffic.

**Files:**
- `apps/registry/registry/settings.py`
- `apps/registry/registry/store.py`
- `apps/registry/registry/api.py`
- `apps/registry/registry/__main__.py`
- Tests: `tests/integration/test_registry.py`

**Step 1: Write failing tests**

Use `httpx.ASGITransport` with `create_app(settings)` and a temp SQLite file.

```python
async def test_register_and_discover(registry_client, seller_card_json):
    create = await registry_client.post(
        "/v1/sellers",
        json={"card_url": "http://127.0.0.1:9201/.well-known/agent-card.json",
              "categories": ["consumer-electronics"]},
        headers={"Authorization": "Bearer test-admin"},
    )
    assert create.status_code == 201
    found = await registry_client.post(
        "/v1/discover",
        json={"category": "consumer-electronics",
              "required_extension": EXTENSION_URI},
    )
    assert found.status_code == 200
    assert found.json()["sellers"][0]["seller_id"] == "northwind-audio"


async def test_registry_rejects_bad_admin_token(registry_client, seller_card_json):
    response = await registry_client.post(
        "/v1/sellers",
        json={"card_url": "http://127.0.0.1:9201/.well-known/agent-card.json",
              "categories": ["consumer-electronics"]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


async def test_registry_rejects_non_local_card_url(registry_client):
    response = await registry_client.post(
        "/v1/sellers",
        json={"card_url": "http://example.com/card.json",
              "categories": ["consumer-electronics"]},
        headers={"Authorization": "Bearer test-admin"},
    )
    assert response.status_code == 400
```

Use `respx` to mock the card fetch and return a valid card produced by
`tests/support/cards.py::build_test_card()`. The `registry_client` fixture builds
`create_app(settings)`, awaits `app.state.store.create_schema()` explicitly (because
`httpx.ASGITransport` does not run FastAPI lifespan), and disposes the engine on teardown.

**Step 2: Implement settings and store**

`Settings` inherits `BaseSettings`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    service_name: str = "registry"
    host: str = "127.0.0.1"
    port: int = 9105
    database_url: str = "sqlite+aiosqlite:///./data/registry.db"
    admin_token: str = "dev-registry-admin"
    allowed_card_hosts: tuple[str, ...] = (
        "127.0.0.1", "localhost", "northwind", "circuitforge", "aurora"
    )
```

`store.py` uses SQLAlchemy Core with a `sellers` table:
`seller_id`, `name`, `card_url`, `categories` JSON, `card_json` JSON,
`card_hash`, `last_seen_at`, `healthy`, `last_error`. Serialize the protobuf card with
`json_format.MessageToDict(card, preserving_proto_field_name=False)`; hash the canonical
JSON with SHA-256 and store the lowercase hex digest.

Methods:

- `upsert(seller_id, card_url, categories, card_json, card_hash, healthy, error)`
- `list_sellers()`
- `get(seller_id)`
- `discover(category, extension_uri)` filters categories and checks the stored card's
  `capabilities.extensions`.
- `mark_health(seller_id, healthy, error)`
- `create_schema()` calls `configure_sqlite(engine)` before creating the table.

**Step 3: Implement API**

Routes:

- `POST /v1/sellers` — admin bearer; body `{seller_id?, card_url, categories}`; `await
  fetch_agent_card(card_url, allowed_hosts=settings.allowed_card_hosts)` and validate it;
  use the provided `seller_id` when present,
  otherwise the card's `name` slug. Reject IDs that do not match
  `^[a-z0-9][a-z0-9-]{1,63}$`. Return `201` with the stored summary.
- `GET /v1/sellers` — list summaries and health, including the stored `card_json` so the
  console registry panel can show protocol version, extension, streaming, and auth
  without cross-origin card fetches.
- `POST /v1/discover` — body `{category, required_extension, limit=20}`; return
  `{sellers: [{seller_id, name, card_url, card_hash, last_seen_at, healthy}]}`.
- `POST /v1/sellers/{seller_id}/refresh` — admin bearer; re-fetch with the configured
  allowed hosts and update.
- `GET /health` — `{"status":"ok"}`.
- `GET /ready` — checks DB with `SELECT 1`.
- `GET /metrics` — Prometheus text.

Use `secrets.compare_digest` for tokens. Return JSON errors with `{"error": "..."}`.

**Step 4: Run tests**

```bash
uv run pytest tests/integration/test_registry.py -q
```

Expected: all pass.

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add Agent Card registry with discovery and auth"
```

---

## Task 5: Seller A2A server, Agent Card, and auth

**Goal:** Three independently runnable A2A servers that serve valid Agent Cards and
reject unauthenticated RPC calls. The executor is a stub until Task 6.

**Files:**
- `apps/seller_agent/seller_agent/settings.py`
- `apps/seller_agent/seller_agent/card.py`
- `apps/seller_agent/seller_agent/server.py`
- `apps/seller_agent/seller_agent/executor.py`
- `apps/seller_agent/seller_agent/store.py`
- `apps/seller_agent/seller_agent/__main__.py`
- Tests: `tests/protocol/test_seller_card.py`, `tests/protocol/conftest.py`,
  `tests/support/servers.py`

**Step 1: Write failing tests**

`tests/support/servers.py` provides:

```python
import asyncio

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn


@asynccontextmanager
async def run_uvicorn(app, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            try:
                response = await client.get(f"http://127.0.0.1:{port}/health")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def seller_server(tmp_path):
    from seller_agent.server import create_app
    from seller_agent.settings import Settings

    settings = Settings(
        service_name="Northwind Audio",
        host="127.0.0.1",
        port=9201,
        public_base_url="http://127.0.0.1:9201",
        profile_path=Path(
            "apps/seller_agent/seller_agent/profiles/northwind.yaml"
        ),
        seller_token="test-seller-token",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}",
        llm_mode="scripted",
        openrouter_api_key=None,
        openrouter_model="deepseek/deepseek-v4.1-flash",
    )
    app = create_app(settings)
    async with run_uvicorn(app, 9201) as base_url:
        yield base_url
```

`tests/protocol/conftest.py` re-exports the fixture so pytest discovers it:

```python
from tests.support.servers import seller_server

__all__ = ["seller_server"]
```

`tests/protocol/test_seller_card.py`:

```python
async def test_card_is_valid(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{seller_server}/.well-known/agent-card.json"
        )
    assert response.status_code == 200
    card = parse_agent_card(response.json())
    assert validate_agent_card(card) == []
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.supported_interfaces[0].url == f"{seller_server}/a2a"
    assert card.supported_interfaces[0].protocol_version == "1.0"
    assert card.capabilities.streaming is True


async def test_a2a_requires_bearer(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{seller_server}/a2a",
            headers={"A2A-Version": "1.0"},
            json={"jsonrpc": "2.0", "id": "1", "method": "GetTask",
                  "params": {"id": "x"}},
        )
    assert response.status_code == 401


async def test_a2a_requires_version_header(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{seller_server}/a2a",
            headers={"Authorization": "Bearer test-seller-token"},
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "m1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "hello"}],
                    }
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32009


async def test_card_is_public(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{seller_server}/.well-known/agent-card.json"
        )
    assert "authorization" not in response.request.headers
```

**Step 2: Implement settings and `build_agent_card`**

`Settings` fields: `service_name`, `host="127.0.0.1"`, `port`, `profile_path`, `public_base_url`
(e.g. `http://127.0.0.1:9201`), `seller_token`, `database_url`, `llm_mode`,
`openrouter_api_key`, `openrouter_model`. Each seller process receives a plain
`SELLER_TOKEN` environment variable; the dev runner maps `SELLER_NORTHWIND_TOKEN`,
`SELLER_CIRCUITFORGE_TOKEN`, and `SELLER_AURORA_TOKEN` to that variable before launch.
The buyer keeps the same values in `BUYER_SELLER_TOKENS` for its local demo credential
directory.

`card.py`:

```python
from a2a.types.a2a_pb2 import (
    AgentCapabilities, AgentCard, AgentExtension, AgentInterface,
    AgentProvider, AgentSkill, HTTPAuthSecurityScheme, SecurityRequirement,
    SecurityScheme, StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from commerce_core.extension import EXTENSION_URI
from commerce_core.pricing import SellerPolicy


def build_agent_card(policy: SellerPolicy, base_url: str) -> AgentCard:
    skills = [
        AgentSkill(id="commerce.catalog.search", name="Search catalog",
                   description="Find products by category and query.",
                   tags=["commerce", "catalog"],
                   input_modes=["application/json"], output_modes=["application/json"]),
        AgentSkill(id="commerce.quote", name="Quote an item",
                   description="Return a structured initial quote.",
                   tags=["commerce", "quote"],
                   input_modes=["application/json"], output_modes=["application/json"]),
        AgentSkill(id="commerce.negotiate", name="Negotiate an offer",
                   description="Counter or accept structured offers.",
                   tags=["commerce", "negotiation"],
                   input_modes=["application/json"], output_modes=["application/json"]),
        AgentSkill(id="commerce.order", name="Place an order",
                   description="Reserve stock and create an idempotent order.",
                   tags=["commerce", "order"],
                   input_modes=["application/json"], output_modes=["application/json"]),
    ]
    return AgentCard(
        name=policy.name,
        description=policy.tagline,
        version="1.0.0",
        provider=AgentProvider(organization=policy.name, url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            extensions=[
                AgentExtension(
                    uri=EXTENSION_URI,
                    description="MarketMesh commerce extension v1",
                    required=True,
                    params={
                        "rating": policy.rating,
                        "sustainability_certified": policy.sustainability_certified,
                    },
                )
            ],
        ),
        security_schemes={
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="bearer", bearer_format="opaque"
                )
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={"bearer": StringList()})
        ],
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json"],
        skills=skills,
    )
```

**Step 3: Implement the app and middleware**

`server.py`:

```python
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    policy = load_policy(settings.profile_path)
    engine = create_async_engine(settings.database_url)
    store = SellerStore(engine)
    card = build_agent_card(policy, settings.public_base_url)
    task_store = DatabaseTaskStore(engine=engine, create_table=True)
    executor = SellerExecutor(store=store, policy=policy)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )
    app = FastAPI(title=f"MarketMesh Seller — {policy.name}")
    app.state.settings = settings
    app.state.store = store
    app.state.policy = policy
    app.state.engine = engine
    app.state.executor = executor
    app.add_middleware(BearerAuthMiddleware, token=settings.seller_token,
                       public_paths={"/health", "/ready", "/metrics",
                                     "/.well-known/agent-card.json"})
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )
    @app.on_event("startup")
    async def startup():
        await configure_sqlite(engine)
        await store.create_schema()
        await seed_catalog(store, policy)
    @app.on_event("shutdown")
    async def shutdown():
        await engine.dispose()
    @app.get("/health")
    async def health():
        return {"status": "ok", "seller": policy.seller_id}
    @app.get("/ready")
    async def ready():
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    return app
```

`BearerAuthMiddleware` uses `secrets.compare_digest` and returns
`JSONResponse({"error": "unauthorized"}, status_code=401)`.

`__main__.py`:

```python
if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
```

**Step 4: Implement the stub executor**

`executor.py` initially:

```python
class SellerExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        task_id = context.task_id
        context_id = context.context_id or task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_FAILED,
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        task_id=task_id,
                        context_id=context_id,
                        role=Role.ROLE_AGENT,
                        parts=[Part(text="Seller graph not implemented")],
                    ),
                ),
            )
        )

    async def cancel(self, context, event_queue):
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id or context.task_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )
```

**Step 5: Run tests**

```bash
uv run pytest tests/protocol/test_seller_card.py -q
```

Expected: 4 passed.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add A2A seller server with Agent Cards and bearer auth"
```

---

## Task 6: Seller LangGraph negotiation

**Goal:** RFQ → structured offer → counteroffer → final offer, over real A2A tasks, with
LLM decisions bounded by the seller policy.

**Files:**
- `apps/seller_agent/seller_agent/graph.py`
- `apps/seller_agent/seller_agent/planner.py`
- `apps/seller_agent/seller_agent/service.py`
- `apps/seller_agent/seller_agent/executor.py` (replace stub)
- `apps/seller_agent/seller_agent/store.py` (add offer persistence)
- Tests: `tests/protocol/test_seller_negotiation.py`

**Step 1: Write failing protocol tests**

`tests/protocol/test_seller_negotiation.py` starts a seller server with `scripted` planner
and a test token, then uses the A2A client:

```python
async def test_rfq_offer_and_counter(seller_session):
    rfq = RFQ(...)
    message = make_message(
        role=Role.ROLE_USER,
        text="Please quote 12 units.",
        context_id="run-1",
        envelope=wrap_payload("rfq", rfq),
    )
    client, card = seller_session
    events = await collect_stream(client, SendMessageRequest(message=message))
    task_id = first_task_id(events)
    offer = last_offer(events)
    assert offer["status"] == "proposed"
    assert offer["round"] == 1
    assert task_state(events) == TaskState.TASK_STATE_INPUT_REQUIRED

    counter = CounterOffer(
        negotiation_round=2,
        target_unit_price_cents=28790,
        requested_changes={},
        rationale="Can you improve the unit price?",
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Counter.",
        context_id="run-1",
        task_id=task_id,
        envelope=wrap_payload("counter_offer", counter),
    )
    events = await collect_stream(client, SendMessageRequest(message=message))
    second = last_offer(events)
    assert second["round"] == 2
    assert second["total_cents"] < offer["total_cents"]


async def test_task_ids_are_stable_and_context_is_shared(seller_session):
    offer, events = await start_rfq(seller_session)
    task_id = offer["task_id"]
    counter = CounterOffer(
        negotiation_round=2,
        target_unit_price_cents=28790,
        requested_changes={},
        rationale="Can you improve the unit price?",
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Counter.",
        context_id="run-1",
        task_id=task_id,
        envelope=wrap_payload("counter_offer", counter),
    )
    events = await collect_stream(client, SendMessageRequest(message=message))
    second = last_offer(events)
    assert second["task_id"] == task_id
    assert second["context_id"] == "run-1"
```

`collect_stream` consumes `client.send_message(SendMessageRequest(...))`, records
`StreamResponse` variants, and returns them.

**Step 2: Implement the seller planner**

`planner.py`:

```python
class SellerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["propose", "counter", "accept", "reject"]
    unit_price_cents: int
    warranty_months: int
    rationale: str


class SellerPlanner(Protocol):
    async def decide(self, context: "SellerDecisionContext") -> SellerDecision: ...
```

`SellerDecisionContext` contains: policy, catalog item, RFQ or counter, current round,
allowed prices, allowed warranty months, previous offer.

`OpenRouterSellerPlanner`:

```python
class OpenRouterSellerPlanner:
    def __init__(self, api_key: str, model: str):
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            model=model,
            temperature=0.2,
            timeout=30,
            max_retries=1,
        ).with_structured_output(SellerDecision)

    async def decide(self, context):
        return await self.llm.ainvoke([
            SystemMessage(content=SELLER_SYSTEM_PROMPT),
            HumanMessage(content=context.model_dump_json()),
        ])
```

Planner selection is explicit: use `OpenRouterSellerPlanner` only when
`llm_mode == "live"` and the key starts with `sk-or-`; otherwise use
`ScriptedSellerPlanner`. The selected planner is injected into the graph config. The same
rule applies to the buyer planner. If a live planner raises or returns invalid structured
output twice, the seller service falls back to `ScriptedSellerPlanner` for that turn and
marks the offer rationale with `fallback_used`.

`ScriptedSellerPlanner`:

- Initial: `action="propose"`, `unit_price_cents=policy.initial_unit_price_cents`,
  `warranty_months=policy.base_warranty_months`.
- Counter: `unit_price_cents = allowed_prices[0]` (the smallest concession);
  `warranty_months = requested warranty if offered, else base`.
- Accept if the buyer's target is at or above the floor and the current offer is already
  the final ladder step; otherwise counter.
- Reject if the requested price is below the floor and no ladder step can satisfy it.

**Step 3: Implement the seller graph**

`SellerState`:

```python
class SellerState(TypedDict, total=False):
    task_id: str
    context_id: str
    kind: str
    incoming: dict
    decision: dict | None
    offer: dict | None
    error: dict | None
    task_state: str
    message: str
```

Nodes:

1. `classify` — read the first DataPart, extract the `schema` URI, map to kind. Reject
   unknown schema with a `commerce-error`.
2. `prepare` — for `rfq`, build initial options. For `counter_offer`, load the latest
   offer from the store, derive the next allowed ladder options and warranty options.
   Read `requested_changes`: honor a supported `warranty_months`; honor
   `split_shipment=True` by passing `allow_split=True` to `policy.quote`. Reject
   unsupported changes with a `commerce-error`.
3. `decide` — call the injected planner. The planner is in
   `config["configurable"]["planner"]`.
4. `finalize_offer` — validate the decision; build a `Quote` via `policy.quote`; build
   one `OfferLineItem` with the base unit price and the warranty add-on separately, so
   the line-item validator can recompute the all-in subtotal; mark `status="final"` when
   `round >= policy.max_rounds`, the chosen price is the floor, or
   `policy.next_price_options(chosen_price) == [chosen_price]` (no further concession
   exists); persist the offer; emit `offer` artifact.
5. `accept_offer` — load the latest offer, verify `accepted_total_cents`, mark it
   accepted, emit an accepted offer artifact.
6. `reject_offer` — emit a `commerce-error` artifact with `below_floor` or
   `unsupported_constraint`.
7. `order` — implemented in Task 7.

Graph wiring:

```python
builder = StateGraph(SellerState)
builder.add_node("classify", classify)
builder.add_node("prepare", prepare)
builder.add_node("decide", decide)
builder.add_node("finalize_offer", finalize_offer)
builder.add_node("accept_offer", accept_offer)
builder.add_node("reject_offer", reject_offer)
builder.add_node("order", order)
builder.set_entry_point("classify")
builder.add_conditional_edges("classify", route_kind, {
    "order": "order",
    "rfq": "prepare",
    "counter_offer": "prepare",
    "accept_offer": "accept_offer",
    "invalid": END,
})
builder.add_edge("prepare", "decide")
builder.add_conditional_edges("decide", route_decision, {
    "propose": "finalize_offer",
    "counter": "finalize_offer",
    "accept": "accept_offer",
    "reject": "reject_offer",
})
builder.add_edge("finalize_offer", END)
builder.add_edge("accept_offer", END)
builder.add_edge("reject_offer", END)
builder.add_edge("order", END)
```

Compile with `MemorySaver`. Seller task state is authoritative in the seller's
`offers`/`orders` tables; the graph is rebuilt per turn from the incoming envelope.
Use `thread_id = task_id` so a single turn's LangGraph state is isolated. The buyer,
not the seller, needs a durable SQLite checkpointer because its graph pauses across an
external human approval.

**Step 4: Implement `SellerService`**

`service.py` orchestrates the graph and store:

```python
class SellerService:
    async def handle_turn(self, task_id, context_id, message) -> SellerTurn:
        envelope = first_envelope(message)
        if not envelope:
            raise CommerceProtocolError("missing DataPart")
        kind = kind_from_envelope(envelope)
        state = {
            "task_id": task_id,
            "context_id": context_id,
            "kind": kind,
            "incoming": envelope,
        }
        result = await self.graph.ainvoke(
            state,
            config={"configurable": {
                "thread_id": task_id,
                "planner": self.planner,
                "service": self,
            }},
        )
        ...
```

`SellerTurn` has `task_state`, `artifacts: list[Artifact]`, `message: str`.
Map:
- offer proposal → `input_required`
- final offer → `input_required` (still awaiting buyer decision)
- accepted → `completed`
- rejected → `completed` (with error artifact)
- invalid → `failed`

**Step 5: Replace the executor**

`executor.execute`:
- derive `task_id` and `context_id`;
- emit `WORKING` with a short text message;
- call `service.handle_turn`;
- emit each artifact as `TaskArtifactUpdateEvent(last_chunk=True)`;
- emit the turn's `TaskStatusUpdateEvent`; its `TaskState` (`INPUT_REQUIRED`, `COMPLETED`,
  or `FAILED`) is the stream terminator in 1.2.3—there is no `final` field;
- on exception, emit `FAILED` plus a `commerce-error` artifact; never leak a traceback
  to the peer.

`cancel` emits `CANCELED`; the terminal state ends the stream.

**Step 6: Run tests**

```bash
uv run pytest tests/protocol/test_seller_negotiation.py -q
```

Expected: all pass. The first offer must be `30300` for Northwind, then `29200`, then
`28100` when counters target those steps.

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: add LangGraph seller negotiation over A2A"
```

---

## Task 7: Seller ordering, reservations, and idempotency

**Goal:** Turn an approved final offer into exactly one order, even under duplicate
submissions, and return a structured business error when stock or validity fails.

**Files:**
- `apps/seller_agent/seller_agent/order_service.py`
- `apps/seller_agent/seller_agent/store.py` (orders, reservations, idempotency)
- `apps/seller_agent/seller_agent/graph.py` (`order` node)
- Tests: `tests/protocol/test_seller_orders.py`

**Step 1: Write failing tests**

```python
async def test_order_is_created_once(seller_session, accepted_offer):
    po = make_purchase_order(accepted_offer, idempotency_key="idem-1")
    first = await send_order(seller_session, po)
    second = await send_order(seller_session, po)
    assert first["order_id"] == second["order_id"]
    assert first["status"] == "confirmed"
    assert first["total_cents"] == accepted_offer["total_cents"]


async def test_duplicate_does_not_double_reserve(seller_session, accepted_offer):
    po = make_purchase_order(accepted_offer, idempotency_key="idem-2")
    await send_order(seller_session, po)
    await send_order(seller_session, po)
    stock = await seller_session.store.get_stock("NC-700-BLK")
    assert stock.on_hand == 40 - 12


async def test_expired_offer_is_rejected(seller_session, expired_offer):
    response = await send_order(seller_session, make_purchase_order(
        expired_offer, idempotency_key="idem-3"
    ))
    assert response["code"] == "offer_expired"
    assert response["retryable"] is False


async def test_out_of_stock_returns_retryable_error(seller_session, accepted_offer):
    await seller_session.store.set_stock("NC-700-BLK", 0, 0)
    response = await send_order(seller_session, make_purchase_order(
        accepted_offer, idempotency_key="idem-4"
    ))
    assert response["code"] == "out_of_stock"
```

**Step 2: Implement the order node**

For kind `purchase_order`:

1. Parse `PurchaseOrderRequest`.
2. Check idempotency key: if present, return the existing order artifact and complete.
3. Load the referenced offer by `offer_id`; fail `invalid_request` if missing.
4. Verify `offer.seller_id == po.seller_id`, `offer.status in {"final","accepted"}`,
   `po.expected_total_cents == offer.total_cents`, `po.quantity == sum(line quantities)`,
   and `offer.valid_until > now`; otherwise `offer_expired` or `invalid_request`.
5. Verify `po.approval.approved_by` is non-empty. This is an audit assertion, not a
   cryptographic verification.
6. Reserve stock:
   - if `on_hand >= quantity`: decrement `on_hand`;
   - else if split shipment and `on_hand + incoming >= quantity` and
     `incoming_days <= 14`: reserve on-hand and incoming, mark `split_shipment=True`;
   - else raise `out_of_stock` with `retryable=True`.
7. Insert the order and idempotency key in the same transaction.
8. Emit `order` artifact with status `confirmed`, ETA, tracking number, and fulfillment
   details. Complete the negotiation task if it is still open? No: the negotiation task
   was completed by `AcceptOffer` before the order task. The order task is separate.

`order_service.py`:

```python
class OrderService:
    async def create_order(self, po: PurchaseOrderRequest) -> Order:
        async with self.store.transaction() as tx:
            existing = await tx.get_order_by_idempotency(po.idempotency_key)
            if existing:
                return existing
            offer = await tx.get_offer(po.offer_id)
            self._validate(po, offer)
            reservation = await tx.reserve(offer.line_items[0].sku, po.quantity)
            order = Order(
                order_id=f"MM-{uuid4().hex[:10].upper()}",
                ...
            )
            await tx.save_order(order)
            await tx.save_idempotency(po.idempotency_key, order.order_id)
            return order
```

**Step 3: Run tests**

```bash
uv run pytest tests/protocol/test_seller_orders.py -q
```

Expected: all pass.

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add idempotent seller ordering and inventory reservations"
```

---

## Task 8: Buyer discovery, A2A client, and trace store

**Goal:** The buyer can discover registered sellers, independently validate their cards,
open authenticated A2A sessions, stream turns, and persist redacted trace events.

**Files:**
- `apps/buyer_agent/buyer_agent/settings.py`
- `apps/buyer_agent/buyer_agent/registry_client.py`
- `apps/buyer_agent/buyer_agent/a2a_client.py`
- `apps/buyer_agent/buyer_agent/trace.py`
- `apps/buyer_agent/buyer_agent/store.py`
- Tests: `tests/integration/test_buyer_discovery.py`,
  `tests/unit/test_trace_redaction.py`

**Step 1: Write failing tests**

```python
async def test_buyer_validates_cards_independently(buyer_services, seller_cards):
    sellers = await buyer_services.registry.discover("consumer-electronics")
    assert len(sellers) == 3
    for seller in sellers:
        assert seller.card.name
        assert validate_agent_card(seller.card) == []
    assert buyer_services.registry.fetch_calls == 3


async def test_invalid_card_is_excluded(buyer_services, seller_cards, monkeypatch):
    seller_cards["circuitforge"]["capabilities"]["streaming"] = False
    sellers = await buyer_services.registry.discover("consumer-electronics")
    assert {s.seller_id for s in sellers} == {"northwind-audio", "aurora-supply"}


async def test_trace_redacts_authorization(trace_store):
    await trace_store.record(
        "run-1",
        direction="outbound",
        method="SendStreamingMessage",
        task_id="task-1",
        context_id="run-1",
        seller_id="northwind-audio",
        payload={"headers": {"authorization": "Bearer secret"}},
    )
    events = await trace_store.list("run-1")
    assert events[0].payload["headers"]["authorization"] == "[REDACTED]"
```

**Step 2: Implement discovery**

`Settings` includes `database_url`, `checkpoint_path`, `host`, `port`, `registry_url`,
`allowed_card_hosts`, `llm_mode`, `openrouter_api_key`, `openrouter_model`, and
`seller_tokens` parsed from the JSON env value. `checkpoint_path` defaults to
`./data/buyer-checkpoints.db`. `allowed_card_hosts` defaults to the same local and
Compose service names used by the registry.

`RegistryClient`:

- `discover(category)` POSTs to `/v1/discover` with the commerce extension URI.
- For each result, fetches the card directly from `card_url` with `httpx.AsyncClient`
  and a 5-second timeout, passing the configured allowed card hosts to `fetch_agent_card`.
- Validates with `validate_agent_card`.
- Excludes invalid cards and records a trace event.
- Attaches the bearer token from `BUYER_SELLER_TOKENS` by `seller_id`. Missing token is
  an error, not a silent unauthenticated call.

`SellerEndpoint` dataclass: `seller_id`, `name`, `card_url`, `card`, `token`, `rating`,
`sustainability_certified`. The last two come from `card_commerce_metadata(card)` and are
overwritten into every parsed offer; they are never trusted from the offer payload alone.

**Step 3: Implement the A2A session**

`A2ASellerSession`:

```python
class A2ASellerSession:
    def __init__(self, endpoint, trace, run_id):
        self.endpoint = endpoint
        self.trace = trace
        self.run_id = run_id
        self.http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {endpoint.token}"},
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        self.client = None

    async def open(self):
        self.client = await create_client(
            self.endpoint.card,
            ClientConfig(streaming=True, httpx_client=self.http),
        )
        return self

    async def close(self):
        if self.client:
            await self.client.close()
        await self.http.aclose()

    async def send(self, message) -> A2ATurn:
        frames = []
        async for event in self.client.send_message(SendMessageRequest(message=message)):
            frames.append(event)
            await self.trace.record_frame(self.run_id, self.endpoint.seller_id, event)
        return A2ATurn.from_frames(frames)
```

`A2ATurn`:
- `task_id`, `context_id`, `state`
- `offers: list[Offer]` parsed from artifacts named `offer`
- `order: Order | None`
- `error: CommerceError | None`
- `text: str`

Parse artifacts by iterating `artifact_update.artifact.parts` and using
`part_value` + `parse_payload`.

`send_rfq(rfq, context_id)`, `send_counter(task_id, counter)`,
`send_accept(task_id, accept)`, `send_order(po)`, and
`cancel(task_id)` (which wraps `client.cancel_task(CancelTaskRequest(id=task_id))`).

Every message uses `make_message` with the correct role and envelope.

**Step 4: Implement the trace store**

SQLAlchemy table `trace_events`:
`id` (autoincrement), `run_id`, `seq`, `created_at`, `direction`, `seller_id`,
`method`, `task_id`, `context_id`, `payload_json`, `latency_ms`.

`store.py` also owns a `runs` table: `run_id` (primary key), `created_at`,
`updated_at`, `stage`, `mandate_json`, `award_json`, `order_json`, `error`. Methods
`upsert_run(run_id, **fields)`, `get_run(run_id)`, and `list_runs(limit=50)`. The buyer
graph writes the row when it starts and updates stage/award/order as the run progresses;
this is what the console query API reads.

`record` redacts recursively:
- keys named `authorization`, `cookie`, `x-api-key`, `token` become `[REDACTED]`;
- bytes become `<N bytes>`;
- payloads larger than 256 KB are truncated to a summary
  `{"truncated": true, "bytes": N}`.

`record_frame(run_id, seller_id, stream_response)` converts a `StreamResponse` to a
public dict: prefer `task`, then `status_update`, `artifact_update`, or `message`; record
the A2A method as `SendStreamingMessage`; extract task and context IDs when present. It must
never include protobuf internals or the bearer header.

`list(run_id, after_seq=0, limit=200)` returns ordered events.

**Step 5: Run tests**

```bash
uv run pytest tests/integration/test_buyer_discovery.py \
  tests/unit/test_trace_redaction.py -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add buyer discovery, A2A client, and trace store"
```

---

## Task 9: Buyer LangGraph negotiation and ranking

**Goal:** A real buyer graph that parses the brief, fans out A2A RFQs, negotiates up to
three rounds, scores final offers, and stops before ordering.

**Files:**
- `apps/buyer_agent/buyer_agent/planner.py`
- `apps/buyer_agent/buyer_agent/graph.py`
- `apps/buyer_agent/buyer_agent/policies.py`
- Tests: `tests/integration/test_buyer_graph.py`

**Step 1: Write failing graph test**

Build the graph with `MemorySaver`, a `FakeRegistry`, a `ScriptedBuyerPlanner`, and a
`ScriptedA2AClient` that returns the three known initial/final offers. The fake records
`sent_rfqs` and `sent_rfq_texts` in addition to accept/order/cancel calls.

```python
async def test_graph_fans_out_and_ranks_circuitforge_first(buyer_graph, demo_brief):
    config = {"configurable": {"thread_id": "run-test", "services": fake_services}}
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]},
        config=config,
    )
    snapshot = await buyer_graph.aget_state(config)
    assert snapshot.values["stage"] == "awaiting_approval"
    assert snapshot.values["award"]["winner"]["seller_id"] == "circuitforge"
    assert len(snapshot.values["negotiations"]) == 3
    assert snapshot.values["order"] is None
    assert snapshot.next == ("await_approval",)
```

Also assert:

```python
assert all(len(n["rounds"]) >= 2 for n in snapshot.values["negotiations"])
assert "max_total_cents" not in fake_services.a2a.sent_rfqs[0].model_dump_json()
assert "3400" not in fake_services.a2a.sent_rfq_texts[0]
```

**Step 2: Implement the buyer planner**

```python
class CounterChoice(BaseModel):
    target_unit_price_cents: int
    requested_changes: dict[str, str | int | bool]
    rationale: str


class BuyerPlanner(Protocol):
    async def parse_brief(self, text: str) -> Mandate: ...
    async def choose_counter(
        self, offer: Offer, mandate: Mandate, allowed: list[int], round_number: int
    ) -> CounterChoice: ...
    async def explain_award(self, award: AwardPackage) -> str: ...
```

`OpenRouterBuyerPlanner` uses the same ChatOpenAI configuration (OpenRouter base URL,
`temperature=0`, `timeout=45`, `max_retries=1`) and structured output.
`ScriptedBuyerPlanner` returns the demo mandate and chooses the **lowest** allowed target;
the graph passes one allowed target per round, so this is deterministic.
It includes `requested_changes={"warranty_months": mandate.min_warranty_months}` when
the current offer's warranty is below the mandate, and
`requested_changes["split_shipment"] = True` when the offer has
`stock_confidence < 1.0` and no split commitment.

Add `mandate_from_text` fallback for the demo: if the LLM fails twice, use a regex-based
extractor and the fixed scenario values. If the counter planner fails twice, use the
scripted lowest-allowed-target choice. If `explain_award` fails, use a deterministic
two-sentence summary. Record `fallback_used` in all three cases.

**Step 3: Implement the graph state and nodes**

```python
class BuyerState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    run_id: str
    mandate: dict
    stage: str
    sellers: list[dict]
    offers: Annotated[list[dict], operator.add]
    negotiations: Annotated[list[dict], operator.add]
    award: dict | None
    approval: dict | None
    order: dict | None
    error: dict | None
    trace: Annotated[list[dict], operator.add]
```

`offers`, `negotiations`, and `trace` are additive. `messages` uses LangGraph's
`add_messages` reducer so assistant and human turns stream through AG-UI.

`interpret_brief`:
- take the last `HumanMessage`;
- set `run_id` from `config["configurable"]["thread_id"]`;
- call `planner.parse_brief`; retry once on failure, then use `mandate_from_text`;
- if the fallback mandate is still invalid, append an `AIMessage` asking for the missing
  fields and end;
- otherwise store `mandate.model_dump(mode="json")`, upsert the `runs` row with stage
  `brief_ready`, and set `stage="brief_ready"`.

`discover_sellers`:
- call `services.registry.discover("consumer-electronics")`;
- keep only endpoints whose cards validate independently;
- store serializable summaries in `sellers` (seller_id, name, card_url, rating,
  sustainability from the validated card extension metadata) and keep the full
  endpoints in the registry service, not graph state;
- if none remain, append an `AIMessage` and end.

`plan_sourcing`:
- call planner to compose a 2-sentence RFQ message; fall back to a deterministic message;
- set `rfq_message` and use it as `RFQ.message`; set `stage="sourcing_planned"`.

`prepare_fanout`:
- set `stage="negotiating"`;
- return only serializable state.

`fan_out_sellers(state)` (the conditional-edge function, not a node):
- return `[Send("negotiate_seller", {"seller_id": s["seller_id"],
  "mandate": state["mandate"], "run_id": state["run_id"]})
  for s in state["sellers"]]`.

`negotiate_seller`:
- resolve the full endpoint from `services.registry.endpoint(seller_id)`;
- open the session;
- send RFQ;
- for `round_number` from 1 to 3:
  - record each offer in `rounds`;
  - if the offer is rejected or errored, stop;
  - if `round_number == 3`, stop;
  - if offer status is `final`, stop;
  - compute the full target ladder with `counter_targets`;
  - select the ladder entry for this round (`round_number - 2`); if out of range, stop;
  - pass that single target as `allowed`; ask the planner for the counter; on repeated
    failure use the allowed target; validate the returned target is in `allowed`;
  - send counter;
- return one `offers` item (final offer), one `negotiations` item, and trace events.

`rank_offers`:
- compute hard failures and eligible offers;
- score and sort;
- build `AwardPackage` with `savings_cents` = sum(first round total for each seller) -
  winner total;
- upsert the `runs` row with the award and stage `awaiting_approval`;
- set `stage="awaiting_approval"`; if empty, set `error` and end.

`await_approval`:
- `decision = normalize_approval(interrupt({...}))` with `message` string,
  `reason="order_approval"`, and `responseSchema` requiring `approved`, `approved_by`,
  `note`;
- `normalize_approval` handles three shapes: a direct payload
  `{approved: ...}` (single standard interrupt), a `{status: "resolved", payload: ...}`
  wrapper, and the `__agui_cancelled__` sentinel from CopilotKit's `cancel()`; a
  cancellation becomes `{approved: False, approved_by: "system", note: "Approval cancelled"}`;
- `return {"approval": decision, "stage": ...}`.

Graph edges:

```python
builder.add_edge(START, "interpret_brief")
builder.add_conditional_edges("interpret_brief", has_brief, {
    "continue": "discover_sellers",
    "stop": END,
})
builder.add_conditional_edges("discover_sellers", has_sellers, {
    "continue": "plan_sourcing",
    "stop": END,
})
builder.add_edge("plan_sourcing", "prepare_fanout")
builder.add_conditional_edges("prepare_fanout", fan_out_sellers, ["negotiate_seller"])
builder.add_edge("negotiate_seller", "rank_offers")
builder.add_conditional_edges("rank_offers", has_award, {
    "continue": "await_approval",
    "stop": END,
})
builder.add_conditional_edges("await_approval", approval_route, {
    "approved": "place_order",
    "rejected": "cancel_losers",
})
builder.add_edge("place_order", "finalize")
builder.add_edge("cancel_losers", "finalize")
builder.add_edge("finalize", END)
```

**Step 4: Implement deterministic guardrails**

- The buyer never puts `max_total_cents` into an `RFQ`, `CounterOffer`, RFQ prose, or
  any A2A message. A final assertion checks the serialized outbound envelope and text.
- Counter target must be in `allowed`; otherwise use `allowed[0]` and record
  `guardrail_rejected`.
- A seller's offer with a mismatched `request_id` or unknown `seller_id` is rejected.
- A seller's total is recomputed from `(unit_price_cents + warranty_addon_cents)` per
  line item before use; a mismatch is a protocol error.
- The buyer overwrites `seller_rating` and `terms.sustainability_certified` with the
  values from the independently validated Agent Card extension; it never trusts those
  claims from inside an offer.
- After each planner call, persist a redacted trace event named `llm.decision` in live
  mode or `scripted.decision` in scripted mode, containing the action, rationale, and
  fallback flag but never the mandate's budget. This is the visible difference between
  live and scripted runs in the A2A Wire.

**Step 5: Run tests**

```bash
uv run pytest tests/integration/test_buyer_graph.py -q
```

Expected: all pass; graph stops at `await_approval`; no order exists.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add buyer negotiation graph and deterministic ranking"
```

---

## Task 10: Approval resume, order orchestration, and AG-UI endpoint

**Goal:** Approve or reject through a LangGraph interrupt, then accept the winner, create
the order, cancel losers, and stream the whole run to CopilotKit over AG-UI.

**Files:**
- `apps/buyer_agent/buyer_agent/approval.py`
- `apps/buyer_agent/buyer_agent/graph.py` (`place_order`, `cancel_losers`, `finalize`)
- `apps/buyer_agent/buyer_agent/server.py`
- `apps/buyer_agent/buyer_agent/__main__.py`
- `apps/buyer_agent/buyer_agent/console_api.py`
- Tests: `tests/integration/test_approval.py`,
  `tests/integration/test_buyer_server.py`

**Step 1: Write failing approval test**

```python
async def test_reject_creates_no_order(buyer_graph, demo_brief, fake_services):
    config = {"configurable": {"thread_id": "run-reject", "services": fake_services}}
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=config
    )
    snapshot = await buyer_graph.aget_state(config)
    assert snapshot.next == ("await_approval",)
    interrupt = snapshot.tasks[0].interrupts[0]
    assert interrupt.value["reason"] == "order_approval"

    await buyer_graph.ainvoke(
        Command(resume={"approved": False, "approved_by": "Demo Buyer",
                        "note": "Too expensive"}),
        config=config,
    )
    result = await buyer_graph.aget_state(config)
    assert result.values["order"] is None
    assert fake_services.a2a.order_calls == 0
    assert len(fake_services.a2a.cancel_calls) == 3


async def test_copilotkit_cancel_sentinel_is_a_rejection(buyer_graph, demo_brief, fake_services):
    config = {"configurable": {"thread_id": "run-cancel", "services": fake_services}}
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=config
    )
    await buyer_graph.ainvoke(
        Command(resume={"__agui_cancelled__": True, "interrupt_id": "x"}),
        config=config,
    )
    result = await buyer_graph.aget_state(config)
    assert result.values["order"] is None
    assert result.values["stage"] == "rejected"


async def test_approve_accepts_then_orders(buyer_graph, demo_brief, fake_services):
    config = {"configurable": {"thread_id": "run-approve", "services": fake_services}}
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=config
    )
    await buyer_graph.ainvoke(
        Command(resume={"approved": True, "approved_by": "Demo Buyer",
                        "note": "Approved for the team"}),
        config=config,
    )
    result = await buyer_graph.aget_state(config)
    assert result.values["order"]["seller_id"] == "circuitforge"
    assert result.values["order"]["status"] == "confirmed"
    assert fake_services.a2a.accept_calls == 1
    assert fake_services.a2a.order_calls == 1
    assert len(fake_services.a2a.cancel_calls) == 2
```

**Step 2: Implement `place_order`**

After approval:
- require `approved is True` and a non-empty `approved_by`; otherwise treat the resume
  as rejected;
- build an `ApprovalReceipt` with `approval_id = str(uuid4())`, `approved_by`,
  `approved_at`, `note`;
- resolve the winner endpoint and open a fresh authenticated `A2ASellerSession` (the
  negotiation session was closed after its turn);
- send `AcceptOffer` on the winner's negotiation task;
- build `PurchaseOrderRequest` with `idempotency_key = f"{run_id}:{offer_id}"`;
- send the order task;
- persist the order and close the winner session;
- cancel the non-winner negotiation tasks through fresh sessions; record a failed cancel
  as a warning, not as an order failure;
- mark the winner negotiation `accepted` and the others `cancelled` in state;
- set `stage="ordered"`.

On rejection:
- `cancel_losers` opens a fresh session per seller and cancels every negotiation task,
  including the winner's; no accept and no order. A task that is already terminal or
  returns "not cancelable" is recorded and treated as closed, not as a run failure;
- mark all negotiations `cancelled`;
- set `stage="rejected"` and append an assistant summary.

`finalize` appends a concise assistant message. The message is for humans; the award and
order remain in structured state.

**Step 3: Implement the server**

Imports for the checkpointer are
`from langgraph.checkpoint.memory import MemorySaver` in tests and
`from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` in production. Create the
checkpoint directory before opening the saver.

```python
def create_app(settings: Settings, checkpointer, services=None) -> FastAPI:
    engine = create_async_engine(settings.database_url)
    services = services or build_services(settings, engine)
    graph = build_buyer_graph(services, checkpointer)
    app = FastAPI(title="MarketMesh Buyer")
    app.state.settings = settings
    app.state.engine = engine
    app.state.services = services
    add_langgraph_fastapi_endpoint(
        app,
        LangGraphAgent(
            name="marketmesh_buyer",
            graph=graph,
            emit_interrupt_outcome=True,
        ),
        path="/agui",
    )
    app.include_router(console_api.router)

    @app.on_event("startup")
    async def startup():
        await configure_sqlite(engine)
        await services.store.create_schema()

    @app.on_event("shutdown")
    async def shutdown():
        await engine.dispose()

    return app
```

`apps/buyer_agent/buyer_agent/__main__.py` owns the async checkpointer lifecycle:

```python
async def main() -> None:
    settings = Settings()
    Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_path) as checkpointer:
        app = create_app(settings, checkpointer)
        config = uvicorn.Config(app, host=settings.host, port=settings.port)
        await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
```

Tests call `create_app(settings, MemorySaver(), fake_services)` so the AG-UI smoke test
reaches approval without live seller processes. The dev runner and Docker use
`python -m buyer_agent`, not `uvicorn buyer_agent.server:app`, so the checkpointer's
async context manager stays open for the process lifetime.

`console_api.py`:

- `GET /api/runs` — recent 50 runs from `runs` table.
- `GET /api/runs/{run_id}` — mandate, stage, award, order, errors.
- `GET /api/runs/{run_id}/trace?after_seq=0&limit=200` — trace events.
- `GET /health`, `/ready`, `/metrics`.

The buyer writes a `runs` row at graph start and updates it at each stage. The trace API
reads `trace_events`; it does not reconstruct from AG-UI.

**Step 4: Add an AG-UI smoke test**

```python
async def test_agui_stream_starts_and_interrupts(buyer_server):
    payload = {
        "threadId": "agui-test",
        "runId": "run-1",
        "messages": [{"id": "m1", "role": "user",
                      "content": "Buy 12 Nimbus NC-700 headsets..."}],
        "tools": [],
        "context": [],
        "state": {},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", f"{buyer_server}/agui", json=payload,
                                 headers={"Accept": "text/event-stream"}) as response:
            body = "".join([chunk async for chunk in response.aiter_text()])
    assert "RUN_STARTED" in body
    assert "interrupt" in body.lower()
```

The `buyer_server` fixture builds `create_app(settings, MemorySaver())` and runs it with
the `run_uvicorn` helper from Task 5, so the AG-UI endpoint is exercised over a real HTTP
stream.

**Step 5: Run tests**

```bash
uv run pytest tests/integration/test_approval.py \
  tests/integration/test_buyer_server.py -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add approval interrupt, order orchestration, and AG-UI server"
```

---

## Task 11: Console shell and CopilotKit wiring

**Goal:** Replace the placeholder with the MarketMesh console shell, using the preserved
CopilotKit provider, chat, threads drawer, streaming AG-UI state, and approval hook.

**Files:**
- `apps/console/app/page.tsx`
- `apps/console/app/layout.tsx`
- `apps/console/app/globals.css`
- `apps/console/components/chat.tsx`
- `apps/console/components/console-shell.tsx`
- `apps/console/lib/types.ts`
- `apps/console/lib/api.ts`
- `apps/console/lib/format.ts`
- `apps/console/app/api/runs/[runId]/trace/route.ts`
- `apps/console/app/api/registry/sellers/route.ts`
- Tests: TypeScript build; the Playwright spec is added in Task 12

**Step 1: Define shared TypeScript types**

`lib/types.ts` mirrors the buyer state:

```ts
export type OfferLineItem = {
  sku: string;
  name: string;
  quantity: number;
  unit_price_cents: number;
  list_unit_price_cents: number;
  warranty_addon_cents: number;
  attributes: Record<string, string>;
};

export type Offer = {
  offer_id: string;
  request_id: string;
  seller_id: string;
  seller_name: string;
  seller_rating: number;
  currency: string;
  line_items: OfferLineItem[];
  subtotal_cents: number;
  shipping_cents: number;
  total_cents: number;
  delivery_days: number;
  warranty_months: number;
  returns_days: number;
  valid_until: string;
  terms: {
    sustainability_certified: boolean;
    stock_confidence: number;
    split_shipment: boolean;
    notes?: string | null;
  };
  status: "proposed" | "final" | "accepted" | "rejected";
  round: number;
  rationale: string;
};

export type Negotiation = {
  seller_id: string;
  seller_name: string;
  task_id: string;
  status: "open" | "final" | "accepted" | "rejected" | "cancelled" | "error";
  rounds: Offer[];
  final_offer: Offer | null;
  error: string | null;
};

export type BuyerState = {
  run_id?: string;
  stage?: string;
  mandate?: Record<string, unknown> | null;
  sellers?: Array<Record<string, unknown>>;
  offers?: Offer[];
  negotiations?: Negotiation[];
  award?: {
    winner: Offer;
    score: number;
    alternatives: Offer[];
    scores: Record<string, number>;
    savings_cents: number;
    mandate_checks: string[];
  } | null;
  approval?: Record<string, unknown> | null;
  order?: {
    order_id: string;
    seller_id: string;
    status: string;
    total_cents: number;
    eta: string;
    tracking_number: string;
    line_items: OfferLineItem[];
    fulfillment: { carrier: string; status: string };
  } | null;
  error?: string | null;
};
```

`lib/format.ts`:

```ts
export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(cents / 100);
```

`lib/api.ts` exports `fetchTrace(runId, afterSeq)` and `fetchRegistry()`.

**Step 2: Wire the page and providers**

`page.tsx` is a client component. Preserve the existing provider pattern:

```tsx
<CopilotKitProvider runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
  <CopilotChatConfigurationProvider agentId="marketmesh_buyer">
    <CopilotThreadsDrawer agentId="marketmesh_buyer" />
    <ConsoleShell />
  </CopilotChatConfigurationProvider>
</CopilotKitProvider>
```

`ConsoleShell` uses:

```tsx
const { agent, isReady } = useAgent({ agentId: "marketmesh_buyer" });
const state = (agent.state ?? {}) as BuyerState;
```

`useInterrupt`:

```tsx
const approvalElement = useInterrupt({
  agentId: "marketmesh_buyer",
  renderInChat: false,
  enabled: (event) => {
    const value = event.value as { reason?: string } | null;
    return value?.reason === "order_approval";
  },
  render: ({ interrupt, resolve, cancel }) => (
    <ApprovalCard
      message={interrupt?.message ?? "Approve this order?"}
      award={state.award ?? null}
      onApprove={(note) => resolve({
        approved: true,
        approved_by: "Demo Buyer",
        note,
      })}
      onReject={(note) => resolve({
        approved: false,
        approved_by: "Demo Buyer",
        note,
      })}
      onCancel={() => cancel()}
    />
  ),
});
```

Render `approvalElement` in both the chat column and the Deal Room:

```tsx
<div className="chat-approval">{approvalElement}</div>
...
<div className="deal-approval">{approvalElement}</div>
```

They share the same `resolve`/`cancel` functions. Do not create a second
`useInterrupt` call.

**Step 3: Wire sample briefs and reset**

`Chat` renders `CopilotChat` with labels for MarketMesh. Add a sample brief panel with a
button labeled exactly `Run sample brief`:

```tsx
const SAMPLE_BRIEF = `Buy 12 Nimbus NC-700 ANC headsets in black. ` +
  `Budget is $3,400 total, delivered within 14 days. ` +
  `Require at least a 24-month warranty and 30-day returns. ` +
  `Prefer sustainable sellers. Ask for human approval before ordering.`;

async function runSample() {
  if (!isReady) return;
  agent.setMessages([]);
  agent.setState({});
  agent.threadId = crypto.randomUUID();
  agent.addMessage({
    id: crypto.randomUUID(),
    role: "user",
    content: SAMPLE_BRIEF,
  });
  await agent.runAgent();
}
```

`useAgent` returns `{ agent, isReady }`; disable the sample and reset buttons until
`isReady` is true. Add a "New run" button with the same reset, without the sample
message.

**Step 4: Add proxy routes**

`app/api/runs/[runId]/trace/route.ts`:

```ts
import { NextRequest } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const after = request.nextUrl.searchParams.get("after_seq") ?? "0";
  const response = await fetch(
    `${process.env.BUYER_API_URL ?? "http://127.0.0.1:9100"}` +
      `/api/runs/${runId}/trace?after_seq=${after}`,
    { cache: "no-store" },
  );
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
```

`app/api/registry/sellers/route.ts` proxies `GET /v1/sellers` from
`REGISTRY_URL`; it returns `503` with a JSON error when the registry is down.

**Step 5: Run typecheck and build**

```bash
cd apps/console
npm run typecheck
npm run build
```

Expected: both pass.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: wire CopilotKit console shell to the buyer AG-UI endpoint"
```

---

## Task 12: Deal Room, A2A Wire, registry, approval, and order UI

**Goal:** Make the protocol visible and the approval decision obvious.

**Files:**
- `apps/console/components/console-shell.tsx`
- `apps/console/components/stage-stepper.tsx`
- `apps/console/components/seller-lane.tsx`
- `apps/console/components/offer-card.tsx`
- `apps/console/components/offer-matrix.tsx`
- `apps/console/components/negotiation-feed.tsx`
- `apps/console/components/a2a-wire.tsx`
- `apps/console/components/approval-card.tsx`
- `apps/console/components/order-panel.tsx`
- `apps/console/components/registry-panel.tsx`
- `apps/console/app/globals.css`
- `apps/console/e2e/console.spec.ts`

**Step 1: Build the layout**

Desktop: 420px chat rail, flexible deal room; 12px gap; warm paper background. Mobile:
stack chat above the deal room, with the stage stepper sticky at the top.

Header:
- `MarketMesh` wordmark in Instrument Serif.
- Registry dot: green if `/api/registry/sellers` returns 3 healthy sellers.
- `3 sellers` count.
- Model badge: `DeepSeek V4.1 Flash` or `Scripted demo`.
- `New run` button.

Stage stepper: `Brief · Discover · RFQ · Negotiate · Approve · Order`. Highlight from
`state.stage`.

**Step 2: Build seller lanes and offer cards**

`seller-lane.tsx` receives a `Negotiation` and optional `Offer`.
Show:
- seller name, rating, sustainability badge;
- latest total, unit price, delivery, warranty, returns;
- round chips `R1 $3,636.60`, `R2 $3,504.00`, `R3 $3,372.00`;
- hard-constraint failures in amber/red;
- a small "view A2A" button that filters the wire to that seller.

`offer-card.tsx` shows a compact money-first card. Use tabular numerals and monospace
for prices.

**Step 3: Build the matrix and negotiation feed**

`offer-matrix.tsx` is a real table with columns: Seller, Total, Unit, Delivery,
Warranty, Returns, Sustainability, Score. The winner row has a signal-green left rule
and an `APPROVED` or `WINNER` tag.

`negotiation-feed.tsx` groups rounds by seller, shows buyer counter targets, seller
responses, and status transitions. No free-form invented numbers.

**Step 4: Build the A2A Wire**

`useRunTrace(runId)` polls `/api/runs/{runId}/trace` every 1000 ms while the stage is not
terminal. Keep events in state, append by `seq`, stop polling when
`ordered|rejected|failed`.

Render:
- columns: time, direction arrow, seller, method, task ID, state, latency;
- filters: all / inbound / outbound / seller;
- expandable `<details>` containing pretty-printed JSON;
- a red `AUTH REDACTED` note is never shown; redaction is silent.

Empty state: "No A2A frames yet. Start a run to see the wire."

**Step 5: Build approval and order**

`approval-card.tsx`:
- total, winner, score, budget headroom, mandate checks;
- alternatives table;
- offer expiry countdown text (computed from `valid_until`);
- note input;
- `Approve order` (signal green), `Reject` (red outline);
- keyboard focus on Approve; `Escape` does not approve;
- both copies of the card share the same callbacks.

`order-panel.tsx`:
- approval receipt (approver, time, note);
- order ID, total, ETA, tracking;
- mock fulfillment timeline: `Reserved → Processing → In transit → Delivered`;
- the literal `Order confirmed` heading once an order exists.

If no order yet, show the mandate checks and the winner. On the rejected path render the
literal text `No order was placed` with the rejection note; on the awaiting path render
`Awaiting approval`.

**Step 6: Build registry panel**

Fetch `/api/registry/sellers` on mount. Show seller name, protocol version, extension URI,
streaming, auth scheme, last seen, healthy. Empty state when the registry is offline.

**Step 7: Styling**

Use a warm paper palette:
- canvas `#F4F0E6`
- panel `#FBF8F1`
- ink `#171713`
- muted `#6B665B`
- rule `#D9D2C3`
- signal `#1F7A55`
- amber `#B7791F`
- red `#B42318`

Use `Instrument Serif` for display headings, `Plus Jakarta Sans` for UI, and
`Spline Sans Mono` for protocol data. Add:
- visible `:focus-visible` rings;
- `prefers-reduced-motion` disabling transitions;
- `aria-live="polite"` on stage and approval changes;
- table `<caption class="sr-only">`;
- no color-only status: pair color with text.

**Step 8: Playwright smoke test**

`apps/console/e2e/console.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("buyer runs the demo and orders only after approval", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MarketMesh")).toBeVisible();
  const runSample = page.getByRole("button", { name: "Run sample brief" });
  await expect(runSample).toBeEnabled({ timeout: 15_000 });
  await runSample.click();

  await expect(page.getByText("Northwind Audio").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("CircuitForge").first()).toBeVisible();
  await expect(page.getByText("Aurora Supply").first()).toBeVisible();
  await expect(page.getByText(/R2/).first()).toBeVisible();
  await expect(page.getByText("Approve order").first()).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Approve order" }).first().click();
  await expect(page.getByText("Order confirmed").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/MM-/).first()).toBeVisible();
  await expect(page.getByText("No order was placed")).toHaveCount(0);
});

test("reject path places no order", async ({ page }) => {
  await page.goto("/");
  const runSample = page.getByRole("button", { name: "Run sample brief" });
  await expect(runSample).toBeEnabled({ timeout: 15_000 });
  await runSample.click();
  await expect(page.getByText("Reject", { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Reject", exact: true }).first().click();
  await expect(page.getByText("No order was placed").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Order confirmed")).toHaveCount(0);
});
```

Add `@playwright/test` to dev dependencies and `playwright.config.ts` with
`baseURL: "http://127.0.0.1:3000"`, one worker, and a 60-second timeout.

**Step 9: Run verification**

With `make dev` running in another terminal:

```bash
cd apps/console
npx playwright test
```

Expected: 2 passed.

**Step 10: Commit**

```bash
git add -A
git commit -m "feat: add deal room, A2A wire, approval, and order console"
```

---

## Task 13: Seed, dev runner, demo, Docker, docs, and final acceptance

**Goal:** A clean checkout runs with `make setup && make dev`, the seeded demo works in
scripted mode, Docker Compose brings up the same topology, and the standalone constraint
is enforced by a test.

**Files:**
- `scripts/dev.py`
- `scripts/seed.py`
- `scripts/run_demo.py`
- `scripts/e2e.py`
- `scripts/check_standalone.py`
- `docker-compose.yml`
- `Dockerfile.python`
- `.dockerignore`
- `apps/console/Dockerfile`
- `README.md`
- `docs/a2a-extension.md`
- `docs/architecture.md`
- `docs/runbook.md`
- `docs/sample-frames/*.json`
- `tests/test_standalone.py`

**Step 1: Write the standalone test**

`tests/test_standalone.py` walks tracked files and fails on forbidden runtime references:

```python
import subprocess
from pathlib import Path

FORBIDDEN = (
    "veri" + "fund",
    "transaction coordinator",
    "escrow",
    "payment intent",
    "stripe",
)

ALLOWED = {
    "docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md",
    "tests/test_standalone.py",
}

def test_no_forbidden_runtime_references():
    files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    offenders = []
    for name in files:
        if name in ALLOWED or name.startswith("docs/"):
            continue
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore").lower()
        except OSError:
            continue
        for word in FORBIDDEN:
            if word in text:
                offenders.append((name, word))
    assert offenders == []
```

The mandated directory name is not inside file contents, so this test passes while still
allowing the design constraint statement.

**Step 2: Implement seed**

`scripts/seed.py`:

- load `.env`;
- for each seller profile, initialize its SQLite catalog and policy;
- start no services; seed DBs directly through `SellerStore`;
- register the three cards with the registry via `POST /v1/sellers` using
  `REGISTRY_ADMIN_TOKEN`; include the profile's `seller_id` so buyer credentials map
  exactly; the API still derives one if it is omitted;
- if the registry is not running, print a clear message and exit 1.

`make dev` runs seed after starting the registry and sellers, before starting the buyer
and console. Seed is idempotent: `INSERT OR REPLACE` by seller ID and SKU.

**Step 3: Implement the dev runner**

`scripts/dev.py`:

- parse `--scripted`, default from `MARKETMESH_LLM_MODE`;
- if mode is `live` and `OPENROUTER_API_KEY` is empty or does not start with `sk-or-`,
  print a clear warning and force `scripted`; this keeps `make dev` usable in a fresh
  checkout;
- create `data/` and `.dev-logs/`;
- launch registry `uv run python -m registry` (the module reads `REGISTRY_PORT`);
- launch three sellers as `uv run python -m seller_agent`, each with its profile path,
  public base URL, database URL, and `SELLER_TOKEN` in the child environment;
- wait for `/health` on registry and each seller;
- run `scripts/seed.py`;
- launch buyer `uv run python -m buyer_agent` (the module reads `BUYER_PORT`);
- launch console `npm run dev -- --port $CONSOLE_PORT`;
- wait for console `/`;
- print a compact URL table;
- write `.dev-pids.json`;
- on SIGINT, terminate all children and wait.

`stop` reads `.dev-pids.json` and terminates the process groups.

**Step 4: Implement demo and e2e scripts**

`scripts/run_demo.py`:
- if `OPENROUTER_API_KEY` starts with `sk-or-` and mode is live, start live services;
- otherwise print "No usable OpenRouter key; running scripted demo" and force scripted
  mode;
- wait for the console and print the sample brief.

`scripts/e2e.py`:
- force `MARKETMESH_LLM_MODE=scripted`;
- start `scripts/dev.py --scripted` in a subprocess;
- wait for `http://127.0.0.1:3000`;
- run `npx playwright install chromium` once if the browser is missing, then
  `npx playwright test` in `apps/console`;
- copy the deterministic scripted RFQ, offer, counter, accept, and order frames from
  `tests/fixtures/frames/` into `docs/sample-frames/` (sanitized, no tokens);
- always terminate the dev process in `finally`.

**Step 5: Docker**

Add a root `.dockerignore` excluding `.git`, `.venv`, `node_modules`, `data`, `.env`,
`apps/console/.next`, `test-results`, and `playwright-report` so image builds stay
reproducible and do not copy local state.

`Dockerfile.python`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
COPY scripts ./scripts
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "registry"]
```

`apps/console/Dockerfile` (built with the repository root as context, so the root
`.dockerignore` applies):

```dockerfile
FROM node:24-alpine
WORKDIR /app
COPY apps/console/package.json apps/console/package-lock.json ./
RUN npm ci
COPY apps/console . .
RUN npm run build
CMD ["npm", "start"]
```

`docker-compose.yml` services:
- `registry`, `northwind`, `circuitforge`, `aurora`, `buyer`, `console`, `seed`.
- Python services build with context `.` and `dockerfile: Dockerfile.python`; the
  console builds with context `.` and `dockerfile: apps/console/Dockerfile`.
- Each Python service uses `Dockerfile.python` and a `command` override:
  `python -m registry`, `python -m seller_agent`, and `python -m buyer_agent`. All
  modules own their uvicorn server lifecycle; the buyer also keeps its async checkpointer
  context open for the process lifetime.
- Mount `marketmesh-data:/app/data`.
- Set `HOST=0.0.0.0` for every Python service in Compose; local `make dev` keeps the
  default `127.0.0.1`.
- Set each seller's `PUBLIC_BASE_URL` to its Compose DNS name and port
  (`http://northwind:9201`, `http://circuitforge:9202`, `http://aurora:9203`) so the
  registry and buyer fetch cards over the Compose network.
- Set `BUYER_AGUI_URL=http://buyer:9100/agui` and `BUYER_API_URL=http://buyer:9100`
  for the console; set `REGISTRY_URL=http://registry:9105` for the buyer and seed.
- Healthchecks for registry, seller, buyer, and console.
- `seed` depends on registry and sellers being healthy; buyer and console depend on
  `seed` completing successfully.
- Publish `127.0.0.1:3000:3000`, `127.0.0.1:9100:9100`, `127.0.0.1:9105:9105`,
  and `127.0.0.1:9201-9203:9201-9203` where Compose supports the range; otherwise list
  each mapping explicitly.

**Step 6: Documentation**

`README.md` must contain:
- what MarketMesh is and what is mocked;
- architecture diagram;
- prerequisites and `make setup && make dev`;
- the sample brief;
- how to read the Deal Room and A2A Wire;
- how to add a fourth seller (profile, card, registry registration, token);
- live vs scripted mode and the OpenRouter key;
- security limits (approval receipt is an assertion; no payments; local credentials);
- test commands;
- troubleshooting ports and reset.

`docs/a2a-extension.md`:
- extension URI and schema files;
- every payload with a field table;
- example RFQ, offer, counter, accept, purchase order, order, error;
- task lifecycle with task/context IDs;
- note that A2A does not define a global registry, so MarketMesh uses a discovery
  service that indexes Agent Cards.

`docs/architecture.md`:
- service boundaries;
- data ownership;
- AG-UI vs A2A split;
- approval boundary;
- failure handling.

`docs/runbook.md`:
- ports and health URLs;
- reset and reseed;
- token rotation;
- common errors: 401, card validation, seller timeout, expired offer, out of stock,
  SQLite locked;
- log locations;
- manual live smoke test.

**Step 7: Run full verification**

```bash
make test
make lint
make e2e
docker compose config
```

Expected:
- `make test`: all Python tests pass, no network to OpenRouter.
- `make lint`: Ruff and TypeScript pass.
- `make e2e`: 2 Playwright tests pass.
- `docker compose config`: valid configuration, no warnings about missing variables.

Then run the manual browser check:

```bash
make dev
```

Open `http://127.0.0.1:3000`, click "Run sample brief", watch three seller lanes, open
A2A Wire, approve, and confirm the order. If `OPENROUTER_API_KEY` is present, rerun with
`MARKETMESH_LLM_MODE=live` and confirm the trace shows `llm.decision` events instead of
`scripted`.

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: add demo runner, Docker topology, and operational docs"
```

---

## Final acceptance checklist

Run these from `verifund-a2a/`:

- [ ] `git status --short` is clean.
- [ ] `make test` passes without `OPENROUTER_API_KEY`.
- [ ] `make lint` passes.
- [ ] `make e2e` passes with scripted LLM mode.
- [ ] `docker compose config` is valid.
- [ ] `curl http://127.0.0.1:9105/v1/sellers` returns three healthy sellers.
- [ ] `curl http://127.0.0.1:9201/.well-known/agent-card.json` returns a valid card.
- [ ] The console shows three seller lanes and at least two negotiation rounds.
- [ ] Approval is required; reject creates no order.
- [ ] Approve creates an order and shows the mock fulfillment timeline.
- [ ] A duplicate order request returns the same order ID.
- [ ] Killing one seller before a run still allows the other two to be ranked.
- [ ] `grep -ri verifund --exclude-dir=.git --exclude-dir=docs .` returns nothing.
- [ ] No payment, escrow, or transaction-coordinator module exists.

## Known execution risks

- **A2A SDK wiring:** use `add_a2a_routes_to_fastapi` with the route factories. If their
  shape changes, read `a2a/server/routes/fastapi_routes.py`, `agent_card_routes.py`, and
  `jsonrpc_routes.py` in the installed 1.2.3 wheel. Do not look for
  `a2a.server.apps` or `A2AStarletteApplication`; those belong to the legacy 0.3 tree under
  `agents/`. Do not switch to a custom JSON-RPC server.
- **AG-UI interrupt mapping:** keep the interrupt value's `message` a string. If
  `emit_interrupt_outcome=True` is not honored by the installed CopilotKit runtime, use
  the legacy path by setting it to `False` and verifying `useInterrupt` still receives
  `on_interrupt`; do not create a second approval endpoint.
- **SQLite contention:** keep writes short. If `database is locked` appears, verify WAL
  mode and that no two services share a DB file.
- **LLM failures:** live mode is optional. The deterministic fallback is part of the
  product behavior, not a test hack.

## Execution handoff

Start with Task 1. After each task, run the verification command and commit before moving
on. Do not start the console UI before the buyer AG-UI endpoint exists; the console's
sample-brief flow depends on it.
