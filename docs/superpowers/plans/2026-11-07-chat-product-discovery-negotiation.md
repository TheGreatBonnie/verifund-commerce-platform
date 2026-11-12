# Chat Product Discovery & Negotiation Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users ask in CopilotKit chat (e.g. "Find me a good laptop for programming under $1500") to discover MarketMesh products, see product cards in chat, and click "Ask agent to negotiate" to clarify a mandate and continue the existing agent-to-agent negotiation workflow in the same thread.

**Architecture:** Add an orchestrator ADK tool that queries buyer marketplace aggregation over HTTP, applies deterministic local filtering/ranking (including a small synonym/attribute table), and returns structured candidates. Render candidates in console chat via `useRenderTool`. The negotiate button sends an in-thread CopilotKit intent message (same pattern as `useRunDetail.startRun`: `agent.addMessage` + `copilotkit.runAgent`); the confirmed brief starts sourcing through the existing middleware tool `send_message_to_a2a_agent` targeting `"MarketMesh Buyer"`. Preserve all existing HITL approvals and settlement behavior.

**Tech Stack:** Python 3.12, FastAPI, Google ADK (`google.adk.tools.FunctionTool`), httpx, pytest/pytest-asyncio; Next.js 16/React 19, TypeScript, `@copilotkit/react-core` v1.79 (`/v2` hooks: `useAgent`, `useCopilotKit`, `useRenderTool`), Zod, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md`

## Global Constraints

- **Grounding (Q8):** Never hallucinate products. Candidates must be a subset/order of marketplace aggregation results; rationale references returned fields only.
- **Local matching (R1):** Do **not** forward generic query terms as registry `q`. Fetch aggregation (optionally by `category`) and match locally with the documented synonym/attribute table. A literal `q=laptop` returns zero rows from the current catalog.
- **Result shape (R7):** CopilotKit may deliver tool results as a JSON string. Normalize string-or-object (same pattern as `parseVerifundToolResult`) before rendering.
- **Negotiation safety:** "Ask agent to negotiate" only starts clarification/brief flow. Do not place orders. Keep `request_award_approval` and all Verifund HITL approvals unchanged. Orchestrator must never reveal/estimate buyer budget to sellers.
- **Scope (Q5):** Card actions are only "Ask agent to negotiate" and "View details/source". No cart/checkout, no navigation.
- **Auth (R6):** Do not expose internal tokens to the browser. Console keeps using its proxy; orchestrator uses server-side HTTP to buyer with `x-verifund-internal-token`. That token is a broad service credential — document it, do not claim least privilege.
- **Instructions (R3):** Update both `MARKETMESH_ORCHESTRATOR_INSTRUCTION` and the CopilotKit middleware `instructions` in `apps/console/app/api/copilotkit/[[...slug]]/route.ts`; `ag_ui_adk` appends the middleware `SystemMessage` after the ADK instruction.
- **Thread (R5):** Negotiate keeps the current chat thread. The buyer creates a new run under the existing A2A `contextId`; no route change.
- **Compatibility:** Keep the `/marketplace` page, `marketmesh:pendingBrief` seeding, `startRun`, and mediated seller/Verifund tool flows working.

## File Map

| Area | File | Responsibility |
|---|---|---|
| Spec | `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md` | Approved design (revised R1–R7). |
| Buyer auth test | `tests/unit/test_buyer_marketplace_auth.py` (new) | Regression: console token and internal token accepted; invalid/missing rejected. No implementation change. |
| Marketplace search | `apps/orchestrator_agent/orchestrator_agent/marketplace.py` (new) | HTTP fetch + synonym table + deterministic filter/rank + grounded result shaping. |
| Orchestrator tool | `apps/orchestrator_agent/orchestrator_agent/agent.py` | Register `search_marketplace_products` `FunctionTool`; wire settings. |
| Orchestrator instruction | `apps/orchestrator_agent/orchestrator_agent/agent.py` (`MARKETMESH_ORCHESTRATOR_INSTRUCTION`) | Discovery, clarification checklist, `send_message_to_a2a_agent` handoff, budget non-disclosure. |
| Middleware instruction | `apps/console/app/api/copilotkit/[[...slug]]/route.ts` | Mirror the new discovery/handoff guidance; cross-reference the ADK instruction. |
| Orchestrator tests | `tests/unit/test_orchestrator_marketplace.py` (new) | Matching/ranking grounding, headline prompt, tool binding, HTTP error handling, instruction wiring. |
| Console card UI | `apps/console/features/chat/product-cards.tsx` (new) | Render results (string or object); negotiate button dispatches in-thread. |
| Console chat wiring | `apps/console/features/chat/chat.tsx` | Register `useRenderTool` for the marketplace search tool. |
| Console card tests | `apps/console/tests/features/chat/product-cards.test.tsx` (new) | String-result parsing/render, grounding, negotiate dispatch. |
| Console wiring test | `apps/console/tests/features/chat/chat.test.tsx` | Assert `search_marketplace_products` renderer is registered; extend hooks mock. |
| Console types (if needed) | `apps/console/lib/types.ts` | Reuse `MarketplaceProduct`; add chat-specific result/`match_rationale` type only if the tool shape differs. |

## Task 1: Pin buyer marketplace dual-token auth (regression only)

**Context:** The endpoint already accepts the internal token (commit `ce78205`, `apps/buyer_agent/buyer_agent/console_api.py:180-200`). Do not re-implement auth. If a test fails, inspect the existing check rather than adding a second one.

**Files:**
- Create: `tests/unit/test_buyer_marketplace_auth.py`

- [ ] **Step 1: Write the regression tests**

Build a minimal FastAPI app that includes `buyer_agent.console_api.router`, sets `app.state.settings` (`console_api_token="console-token"`, `internal_api_token="internal-token"`) and `app.state.services` (a fake with `registry`). Cover:

- valid `x-marketmesh-console-token` → 200
- valid `x-verifund-internal-token` → 200
- neither header → 401
- wrong console token → 401
- wrong internal token → 401
- both tokens → 200
- successful call passes `category` and `q` through to `registry.marketplace_products` (assert the fake was called with the query values)

Use `httpx.ASGITransport`/`AsyncClient` or FastAPI `TestClient` consistent with `tests/integration/test_buyer_settlement_api.py`.

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/unit/test_buyer_marketplace_auth.py -v
```

Expected: PASS immediately. If any case fails, fix the test scaffolding (app state shape/route path) first; only touch `console_api.py` if the existing auth is genuinely broken, and note it in the commit message.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_buyer_marketplace_auth.py
git commit -m "test(buyer): pin marketplace dual-token auth"
```

## Task 2: Deterministic marketplace search + matching module (TDD)

**Files:**
- Create: `apps/orchestrator_agent/orchestrator_agent/marketplace.py`
- Create: `tests/unit/test_orchestrator_marketplace.py`

- [ ] **Step 1: Write the failing tests**

Test pure functions (no network) using a fixture modeled on the real catalog:

```python
MACBOOK = {
    "id": "MM-MACBOOK-AIR-M4-13",
    "sku": "MM-MACBOOK-AIR-M4-13",
    "name": "MacBook Air M4 13-inch",
    "category": "Electronics",
    "description": "Apple M4 · 16GB memory · 256GB SSD · Space Gray",
    "unit_price_cents": 99900,
    "original_unit_price_cents": 119900,
    "rating": 4.6,
    "offers": [
        {"seller_id": "northwind-audio", "seller_name": "Northwind Audio",
         "unit_price_cents": 99900, "currency": "USD",
         "available": True, "on_hand": 8, "incoming": 0},
    ],
}

MONITOR = {  # no laptop vocabulary; must not match query="laptop"
    "id": "MM-4K-MONITOR-27", "sku": "MM-4K-MONITOR-27",
    "name": "27-inch 4K USB-C Monitor", "category": "Electronics",
    "description": "4K UHD · USB-C hub · Height adjustable",
    "unit_price_cents": 49900, "original_unit_price_cents": None,
    "rating": 4.7,
    "offers": [{"seller_id": "northwind-audio", "seller_name": "Northwind Audio",
                "unit_price_cents": 49900, "currency": "USD",
                "available": False, "on_hand": 0, "incoming": 0}],
}

CHAIR = {  # different category, unavailable
    "id": "MM-ERGONOMIC-MESH-CHAIR", "sku": "MM-ERGONOMIC-MESH-CHAIR",
    "name": "Ergonomic Mesh Office Chair", "category": "Home & Living",
    "description": "Adjustable lumbar support · Breathable mesh",
    "unit_price_cents": 27900, "original_unit_price_cents": 34900,
    "rating": 4.6,
    "offers": [{"seller_id": "aurora-supply", "seller_name": "Aurora Supply",
                "unit_price_cents": 27900, "currency": "USD",
                "available": True, "on_hand": 4, "incoming": 0}],
}
```

Cases:

- **Headline prompt (extracted constraints):** `filter_and_rank_products([MACBOOK, MONITOR, CHAIR], query="laptop", use_case="programming", max_unit_price_cents=150000)` returns only `MM-MACBOOK-AIR-M4-13`; `shape_search_result(...)` reports `total_candidates == 1`. This must not rely on the word "laptop" appearing in the product data.
- **Literal prompt tolerance:** `query="Find me a good laptop for programming under $1500"` also matches the MacBook. The hard filter requires **any** expanded token to match, so filler words must not suppress a valid match.
- **Synonyms:** `query="notebook"` matches the MacBook; `use_case="programming"` **alone** (no query) ranks the MacBook first without filtering out the monitor or chair.
- **Price ceiling:** 90000 excludes the MacBook (99900).
- **In-stock filter:** an all-unavailable product is excluded when `in_stock_only=True`.
- **Grounding:** every returned `sku` is in the input; no synthesized products.
- **Deterministic order:** equal-score products order by `unit_price_cents` then `sku`; run twice and compare exact sequences.
- **Empty input / empty match:** returns `[]` without raising.
- **`match_rationale`:** deterministic list derived from matched fields/tokens; no sentences asserting unreturned facts.
- **Fetch helper:** with `httpx.MockTransport`, `fetch_marketplace_products(base_url=..., internal_token=..., timeout=..., category="Electronics")` requests `GET /api/marketplace/products`, sends `x-verifund-internal-token`, forwards `category`, and sends **no `q` parameter**; unwraps `{"products": [...]}`. A 502/malformed body raises an exception the tool can catch.
- **`shape_search_result`:** takes the full ranked list, reports `total_candidates = len(products)` (post-hard-filter, pre-limit) and truncates the returned `products` slice to `limit`; `applied_filters` echoes effective values.
- **Currency:** each shaped product carries `currency` derived from `offers[0].currency`, defaulting to `USD` when absent.

Run:

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -v
```

Expected: FAIL (module/functions missing).

- [ ] **Step 2: Implement the minimal module**

`marketplace.py` should contain:

```python
async def fetch_marketplace_products(
    *, base_url: str, internal_token: str, timeout: float,
    category: str | None = None,
) -> list[dict]: ...

def filter_and_rank_products(
    products: list[dict], *, query: str | None = None,
    category: str | None = None, max_unit_price_cents: int | None = None,
    in_stock_only: bool = False, use_case: str | None = None,
    preferences: list[str] | None = None,
) -> list[dict]:
    """Return every match, ranked. No truncation: callers shape the page."""

def shape_search_result(
    applied_filters: dict, products: list[dict], limit: int = 12,
) -> dict:
    """Set total_candidates to len(products), then truncate products to limit."""
```

Rules:

- `fetch_marketplace_products` calls `f"{base_url.rstrip('/')}/api/marketplace/products"` with `params={"category": category}` only when provided; `headers={"x-verifund-internal-token": internal_token}`; `response.raise_for_status()`; unwrap `products`; validate it is a list.
- **Synonym/attribute table** (module constant, documented as a demo heuristic):

  ```python
  TOKEN_SYNONYMS = {
      "laptop": ("macbook", "notebook", "portable computer"),
      "notebook": ("macbook", "laptop"),
      "programming": ("memory", "ssd", "cpu", "m4", "developer"),
      "developer": ("memory", "ssd", "cpu", "m4", "programming"),
  }
  ```

  Expansion applies to query/use_case/preference tokens; matching fields are `name`, `description`, `category`, and seller names.
- **Hard filters:** query token match (expanded), category equality, price ceiling, availability.
- **Integer scoring and tiebreak exactly as specified** in the design (`+4/+2/+1/+2/+1/+1`, order `(-score, unit_price_cents, sku)`).
- Return copies (`dict(product)`) with optional `match_rationale` and a product-level `currency` (`offers[0].currency` or `USD`); never mutate inputs.
- Keep logic explicit and testable. No LLM calls, no floats.

Run:

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/marketplace.py tests/unit/test_orchestrator_marketplace.py
git commit -m "feat(orchestrator): add grounded marketplace search and ranking"
```

## Task 3: Register orchestrator search tool (TDD)

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Modify: `tests/unit/test_orchestrator_marketplace.py`

- [ ] **Step 1: Write the failing tool-binding test**

Add a test that builds the tool through a helper (mirroring `_build_mediation_tool`) and asserts:

- `tool.name == "search_marketplace_products"`
- parameters include `query`, `category`, `max_unit_price_cents`, `in_stock_only`, `use_case`, `preferences`, `limit` (and no token/URL parameters)
- the callable uses `settings.buyer_internal_url`, `settings.buyer_internal_token`, `settings.buyer_internal_timeout_seconds` (monkeypatch `marketplace.fetch_marketplace_products` and capture the kwargs)
- a mocked aggregation payload returns `products` grounded to that payload
- `max_unit_price_cents="150000"` (string) is coerced to int; `limit` is clamped to 1–24
- an upstream exception returns `{"error": "marketplace_unavailable", ...}` without tokens or internal URLs

Call the wrapped function via `tool.func(...)` (ADK `FunctionTool` exposes `.func` and `.name`), wrapped in `pytest.mark.asyncio`.

Run:

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -v
```

Expected: FAIL.

- [ ] **Step 2: Implement the tool**

Add to `agent.py`:

```python
def _build_marketplace_search_tool(settings: Settings) -> FunctionTool:
    async def search_marketplace_products(
        query: Optional[str] = None,      # noqa: UP045
        category: Optional[str] = None,   # noqa: UP045
        max_unit_price_cents: Optional[int] = None,  # noqa: UP045
        in_stock_only: bool = False,
        use_case: Optional[str] = None,   # noqa: UP045
        preferences: Optional[list[str]] = None,     # noqa: UP045
        limit: int = 12,
    ) -> dict:
        """Find products from MarketMesh sellers for a grounded purchase search."""
        ...
    return FunctionTool(search_marketplace_products)
```

Notes:

- **Use `Optional[...]`, not `X | None`** — ADK's automatic function parser rejects PEP 604 unions (see the existing `verifund_checkout` comment).
- Coerce `max_unit_price_cents`/`limit` defensively; clamp `limit` to `1..24`.
- Import the module in `agent.py` (`from orchestrator_agent import marketplace`) and call `marketplace.fetch_marketplace_products(...)` / `marketplace.filter_and_rank_products(...)` / `marketplace.shape_search_result(...)`. Module-level access keeps `monkeypatch.setattr(marketplace, "fetch_marketplace_products", ...)` effective in tests.
- Rank the full list, then pass it and the clamped `limit` to `marketplace.shape_search_result(...)`, which sets `total_candidates` before truncating.
- Catch `Exception`, log server-side, and return a structured error payload with no secrets.

Register in `build_agent`:

```python
tools = [
    _build_mediation_tool(settings),
    _build_marketplace_search_tool(settings),
    AGUIToolset(),
]
```

Keep `mediate_seller_call` and all Verifund tools unchanged.

Run:

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py tests/unit/test_orchestrator_marketplace.py
git commit -m "feat(orchestrator): expose marketplace product search tool"
```

## Task 4: Update both instruction surfaces for discovery + handoff

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` (`MARKETMESH_ORCHESTRATOR_INSTRUCTION`)
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts` (`instructions`)
- Modify: `tests/unit/test_orchestrator_marketplace.py`

- [ ] **Step 1: Add the failing instruction test**

Add a test asserting the ADK instruction contains the exact wiring strings:

```python
assert "search_marketplace_products" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
assert "send_message_to_a2a_agent" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
assert "MarketMesh Buyer" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
```

Run `uv run pytest tests/unit/test_orchestrator_marketplace.py -v`; expect FAIL until Step 2.

- [ ] **Step 2: Extend the ADK instruction**

Add a section (keep it concise, do not restate the existing HITL/Verifund protocol):

- **Product discovery:** for find/search/browse requests, call `search_marketplace_products` with extracted constraints (e.g. "$1500" → `max_unit_price_cents=150000`; "under $1500" is a per-unit ceiling in this demo). Pass product/category terms (e.g. `query="laptop"`), not filler words like "good" or "me". Never route discovery to `send_message_to_a2a_agent` or to a seller.
- **Grounding:** present only returned products/SKUs; use `match_rationale` only to explain returned fields.
- **Card context:** when the user asks to negotiate for a shown card, read SKU/name/price/offers from the user message; do not re-search unless constraints changed.
- **Clarification checklist:** quantity (default 1), user-stated budget ceiling/target, delivery deadline, warranty, returns, must-haves. Ask only for fields that are **missing or ambiguous**; never re-ask a field already stated (the sample brief stays one-shot).
- **Confirmed brief / run start:** call `send_message_to_a2a_agent` with `agentName="MarketMesh Buyer"` and a `task` string containing the confirmed mandate plus grounded product context (SKU, name, unit price, offers). Stay in the current thread; do not navigate. Do not place orders or create award/order outcomes.
- **Non-negotiables preserved:** never reveal/estimate buyer budget to sellers; mediated seller calls stay sequential; `request_award_approval` is required before order; Verifund rules unchanged.

- [ ] **Step 3: Mirror the guidance in the middleware instruction**

In `apps/console/app/api/copilotkit/[[...slug]]/route.ts`, add the same discovery / card-context / clarification / `send_message_to_a2a_agent` ("MarketMesh Buyer") bullets to the middleware `instructions` string. Add a one-line comment at both sites pointing at each other, noting that `ag_ui_adk` appends the middleware instruction after the ADK instruction.

- [ ] **Step 4: Run the regression suites**

```bash
uv run pytest tests/unit/test_orchestrator_marketplace.py tests/unit/test_orchestrator_mediation.py tests/unit/test_orchestrator_server.py -v
grep -c "search_marketplace_products" "apps/console/app/api/copilotkit/[[...slug]]/route.ts"
grep -c "MarketMesh Buyer" "apps/console/app/api/copilotkit/[[...slug]]/route.ts"
```

Expected: pytest PASS; both `grep` counts are at least 1.

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py apps/console/app/api/copilotkit/[[...slug]]/route.ts tests/unit/test_orchestrator_marketplace.py
git commit -m "feat(orchestrator): guide chat product discovery and negotiation clarification"
```

## Task 5: Console chat renders product cards and negotiate intent (v2 hooks, TDD)

**Files:**
- Create: `apps/console/features/chat/product-cards.tsx`
- Modify: `apps/console/features/chat/chat.tsx`
- Create: `apps/console/tests/features/chat/product-cards.test.tsx`
- Modify: `apps/console/tests/features/chat/chat.test.tsx`

- [ ] **Step 1: Write the failing card tests**

Create `product-cards.test.tsx`. Mock `@copilotkit/react-core/v2`:

```tsx
const hooks = vi.hoisted(() => ({
  addMessage: vi.fn(),
  runAgent: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: { addMessage: hooks.addMessage } }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));
```

Render `<ProductSearchCards status="complete" result={JSON.stringify(payload)} />` and assert:

- product name, formatted price and currency, seller, availability render
- a JSON **string** result parses (the real backend shape), and an object result also works
- only grounded products appear (payload with two items renders exactly those)
- clicking "Ask agent to negotiate" calls `addMessage` with `role: "user"` and content containing the SKU, then calls `runAgent`
- empty `products` renders the "No matching products" state
- while dispatch is pending, the button is disabled (assert via a deferred promise)

Add a registration test in `chat.test.tsx`:

```ts
const renderNames = hooks.useRenderTool.mock.calls.map(([tool]) => tool.name);
expect(renderNames).toContain("search_marketplace_products");
```

Extend that file's mock with `useCopilotKit` and a configurable `useAgent` so it does not break when the card hook is imported.

Run:

```bash
cd apps/console && pnpm test -- tests/features/chat
```

Expected: FAIL (component missing).

- [ ] **Step 2: Implement `product-cards.tsx`**

- Export `ProductSearchCards({ status, result }: { status?: string; result?: unknown })`.
- Normalize results with the existing **string-or-object** pattern (`parseVerifundToolResult` in `verifund-tools.tsx`, or a local equivalent that also tolerates `"A2A Agent Response: "` prefixes).
- Render current data only: name, emoji/color, price (currency from `product.currency ?? offers[0]?.currency ?? "USD"`), availability summary, key attributes (description/rating), seller/offers, optional `match_rationale`.
- Actions: **View details/source** toggles inline details; **Ask agent to negotiate** uses `useAgent({agentId:"marketmesh_orchestrator"})` + `useCopilotKit()`:

  ```ts
  agent.addMessage({ id: crypto.randomUUID(), role: "user", content: intent });
  await copilotkit.runAgent({ agent });
  ```

  Build `intent` from the product's SKU, name, unit price and offers plus a request to clarify the mandate. Guard with local `isDispatching`, show inline errors, never navigate, never call order/seller endpoints.
- Use existing `mm-*` classes and keep the card compact.

- [ ] **Step 3: Wire `useRenderTool` in `chat.tsx`**

```ts
useRenderTool({
  name: "search_marketplace_products",
  parameters: z.object({
    query: z.string().optional(),
    category: z.string().optional(),
    max_unit_price_cents: z.number().optional(),
    in_stock_only: z.boolean().optional(),
    use_case: z.string().optional(),
    preferences: z.array(z.string()).optional(),
    limit: z.number().optional(),
  }),
  render: ({ status, result }) => (
    <ProductSearchCards status={status} result={result} />
  ),
});
```

Keep the parameters schema concrete (no `.optional()` on the schema itself).

- [ ] **Step 4: Run console tests and typecheck**

```bash
cd apps/console && pnpm test -- tests/features/chat && pnpm typecheck
```

Expected: PASS both.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/product-cards.tsx apps/console/features/chat/chat.tsx \
  apps/console/tests/features/chat/product-cards.test.tsx apps/console/tests/features/chat/chat.test.tsx
git commit -m "feat(console): render marketplace product cards in chat"
```

(Include `apps/console/lib/types.ts` only if a chat-specific type was added.)

## Task 6: Verify the in-thread run handoff (no open-ended fixes)

**Files:**
- Verify (no breaking changes): `apps/console/features/deal-room/hooks/use-run-detail.ts`, `apps/console/features/deal-room/run-detail.tsx`, `apps/console/features/deal-room/console-shell.tsx`, `apps/console/app/(console)/marketplace/page.tsx`
- Verify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts`

- [ ] **Step 1: Confirm each link in the chain**

Record the result of each check in the commit message or PR notes:

1. The middleware appends `send_message_to_a2a_agent` and forwards the chat `threadId` as the A2A `contextId` (middleware dist / `route.ts`). This is the only run-start path used by the confirmed brief.
2. The buyer treats a message without a nested `approval` key as a new sourcing brief (ADK instruction, approval section), so a new run is created under the existing context.
3. `request_award_approval` remains registered as a thread-level `useHumanInTheLoop` tool in `chat.tsx` and is not scoped to a run route.
4. `/marketplace` still sets `marketmesh:pendingBrief` and navigates; `useRunDetail` still consumes and clears it once per route.
5. A card click on `/agents/[runId]` dispatches without navigation: `product-cards.tsx` imports no router, and the card test asserts only `addMessage` + `runAgent` were called.

- [ ] **Step 2: If a link is broken**

Only an instruction/tool-wiring fix that reuses `send_message_to_a2a_agent` is in scope. Do **not** add a second run-start mechanism, change routing, or alter buyer protocol. If the existing path cannot work, stop and update this plan before proceeding.

- [ ] **Step 3: Run the automated checks**

```bash
uv run pytest tests/unit/test_buyer_marketplace_auth.py tests/unit/test_orchestrator_marketplace.py \
  tests/unit/test_orchestrator_mediation.py -v
cd apps/console && pnpm test -- tests/features/chat && pnpm typecheck
```

Expected: PASS.

- [ ] **Step 4: Commit verification fixes (only if Step 2 produced changes)**

```bash
git add -A
git commit -m "fix: align chat discovery negotiation handoff with existing run flow"
```

## Task 7: Final verification report

- [ ] **Step 1: Manual smoke checklist (document in PR/notes)**

1. Start the stack per the project runbook (console + orchestrator + buyer + registry + sellers).
2. In chat, send: `Find me a good laptop for programming under $1500`.
3. Verify cards render grounded to MarketMesh catalog: the MacBook Air (offers from its sellers) and nothing invented; "laptop" matching is explained by the synonym table, not by fabricated data.
4. Click `Ask agent to negotiate` on a card; verify same-thread clarification asks only for missing mandate fields and does not re-ask what the message already states.
5. Confirm the mandate; verify the buyer creates a new run, negotiation proceeds in the thread, and `request_award_approval` appears before any order.
6. Send a complete time-boxed brief directly (existing sample brief) and verify it still starts without extra questions.
7. Verify `/marketplace` "Ask agent to negotiate" still works end to end.

- [ ] **Step 2: Summarize evidence**

Report: tests run and results, typecheck result, files changed, and known limitations:

- synonym/attribute matching is a deterministic demo heuristic (catalog tags migration listed as follow-up);
- `total_candidates` counts post-filter, pre-limit;
- the console route does not change for the new run (R5);
- internal token is a broad service credential (R6);
- no live currency/locale context.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-07-chat-product-discovery-negotiation.md`.

**Spec (revised):** `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md`

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks (`superpowers:subagent-driven-development`).
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans` with checkpoints.

Which approach? Reply `1` for Subagent-Driven or `2` for Inline Execution.
