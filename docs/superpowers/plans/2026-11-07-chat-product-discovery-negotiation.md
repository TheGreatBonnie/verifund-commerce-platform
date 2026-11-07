# Chat Product Discovery & Negotiation Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users ask in CopilotKit chat (e.g. "Find me a good laptop for programming under $1500") to discover MarketMesh products, see product cards in chat, and click "Ask agent to negotiate" to clarify a mandate and continue the existing agent-to-agent negotiation workflow in the same thread.

**Architecture:** Add an orchestrator ADK tool that queries buyer marketplace aggregation over HTTP, applies deterministic grounded filtering/ranking, and returns structured candidates. Render candidates in console chat via `useRenderTool`. The negotiate button sends an in-thread CopilotKit intent message (same pattern as `useRunDetail.startRun`: `agent.addMessage` + `copilotkit.runAgent`) so the orchestrator can collect mandate fields and issue a confirmed brief that continues the existing negotiation/run flow. Preserve all existing HITL approvals and settlement behavior.

**Tech Stack:** Python 3.12, FastAPI, Google ADK (`google.adk.tools.FunctionTool`), httpx, pytest/pytest-asyncio; Next.js 16/React 19, TypeScript, `@copilotkit/react-core` v1.79 (`/v2` hooks: `useAgent`, `useCopilotKit`, `useRenderTool`), Zod.

**Spec:** `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md`

## Global Constraints

- **Grounding (Q8):** Never hallucinate products. Candidates must be a subset/order of marketplace aggregation results; rationale references returned fields only.
- **Negotiation safety:** "Ask agent to negotiate" only starts clarification/brief flow. Do not place orders. Keep `request_award_approval` and all Verifund HITL approvals unchanged. Orchestrator must never reveal/estimate buyer budget to sellers.
- **Scope (Q5):** Card actions are only "Ask agent to negotiate" and "View details/source". No cart/checkout.
- **Auth:** Do not expose internal tokens to the browser. Console keeps using its proxy; orchestrator uses server-side HTTP to buyer with internal auth.
- **Compatibility:** Keep existing `/marketplace` page, `marketmesh:pendingBrief` seeding, `startRun`, and mediated seller/Verifund tool flows working.

## File Map

| Area | File | Responsibility |
|---|---|---|
| Spec | `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md` | Approved design (done). |
| Buyer auth | `apps/buyer_agent/buyer_agent/console_api.py` | Allow internal-token access to marketplace aggregation for orchestrator (backward-compatible). |
| Buyer auth test | `tests/unit/test_buyer_marketplace_auth.py` (new) | Verify console token still works and internal token is accepted/rejected correctly. |
| Orchestrator settings | `apps/orchestrator_agent/orchestrator_agent/settings.py` | Buyer internal URL/token/timeout already exist; add only if needed (prefer reuse). |
| Marketplace search | `apps/orchestrator_agent/orchestrator_agent/marketplace.py` (new) | HTTP fetch + deterministic filter/rank + grounded result shaping. |
| Orchestrator tool | `apps/orchestrator_agent/orchestrator_agent/agent.py` | Register `search_marketplace_products` `FunctionTool`; wire settings. |
| Orchestrator instruction | `apps/orchestrator_agent/orchestrator_agent/agent.py` (`MARKETMESH_ORCHESTRATOR_INSTRUCTION`) | Product discovery, mandate clarification checklist, confirmed brief/runs continuation, budget non-disclosure. |
| Orchestrator tests | `tests/unit/test_orchestrator_marketplace.py` (new) | Filter/rank grounding, tool binding, HTTP error handling. |
| Console card UI | `apps/console/features/chat/product-cards.tsx` (new) | Render `search_marketplace_products` results; negotiate button sends in-thread intent. |
| Console chat wiring | `apps/console/features/chat/chat.tsx` | Register `useRenderTool` for marketplace search tool. |
| Console types (if needed) | `apps/console/lib/types.ts` | Reuse/extend `MarketplaceProduct` or add chat-specific result type if tool shape differs. |

## Task 1: Buyer marketplace endpoint accepts orchestrator internal auth (TDD)

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/console_api.py`
- Create: `tests/unit/test_buyer_marketplace_auth.py`

- [ ] **Step 1: Write the failing auth tests**

Create `tests/unit/test_buyer_marketplace_auth.py` with FastAPI `TestClient`/ASGI tests against `buyer_agent` app factory or a minimal app using `console_api.router` and mocked `request.app.state.settings/services/registry`. Cover:
- valid `x-marketmesh-console-token` → 200 (existing behavior)
- valid `x-verifund-internal-token` with `settings.internal_api_token` → 200 (new)
- missing/invalid tokens → 401
- keep `registry.marketplace_products` called with `category`/`query` params.

Run: `uv run pytest tests/unit/test_buyer_marketplace_auth.py -v`
Expected: FAIL because internal token path is not accepted yet (or test scaffolding needs adjustment to actual app state shape).

- [ ] **Step 2: Implement minimal backward-compatible auth**

In `marketplace_products` (`console_api.py`), accept either:
- console token: `x-marketmesh-console-token` matches `settings.console_api_token`, OR
- internal token: `x-verifund-internal-token` matches `settings.internal_api_token` (reuse `_check_internal_token` logic style, but do not break console path).

Use `secrets.compare_digest` for both. Return 401 only if neither valid.

Run: `uv run pytest tests/unit/test_buyer_marketplace_auth.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/buyer_agent/buyer_agent/console_api.py tests/unit/test_buyer_marketplace_auth.py
git commit -m "feat(buyer): allow internal token for marketplace aggregation"
```

## Task 2: Deterministic marketplace search + ranking module (TDD)

**Files:**
- Create: `apps/orchestrator_agent/orchestrator_agent/marketplace.py`
- Create: `tests/unit/test_orchestrator_marketplace.py`

- [ ] **Step 1: Write failing unit tests for filtering/ranking/grounding**

In `tests/unit/test_orchestrator_marketplace.py`, test pure functions (no network): e.g. `filter_and_rank_products(products, query=..., category=..., max_unit_price_cents=..., in_stock_only=..., use_case=..., preferences=..., limit=...)`.
Cases:
- price ceiling excludes products above 150000 cents
- query/category text matches name/category/description (case-insensitive)
- in-stock filter uses offer availability/stock fields present in aggregation
- "programming" use_case boosts relevant grounded terms only if present; does not invent products/fields
- result includes only IDs/SKUs from input; stable ordering deterministic
- empty input/empty match returns empty list with no crash.

Run: `uv run pytest tests/unit/test_orchestrator_marketplace.py -v`
Expected: FAIL (module/functions missing).

- [ ] **Step 2: Implement minimal module**

Create `marketplace.py` with:
- `async def fetch_marketplace_products(*, base_url, internal_token, timeout, category=None, query=None) -> list[dict]` using `httpx.AsyncClient`, header `x-verifund-internal-token`.
- `def filter_and_rank_products(products, *, query=None, category=None, max_unit_price_cents=None, in_stock_only=False, use_case=None, preferences=None, limit=12) -> list[dict]`:
  - normalize text; apply hard filters
  - compute deterministic score from grounded signals (text overlap/relevance tokens from query/use_case/preferences, rating, availability, value)
  - return copies of matched product dicts (preserve source fields; optionally add `match_rationale` string/list derived from matched fields)
- `def shape_search_result(applied_filters, products, total_candidates) -> dict` for tool output.

Keep logic simple, explicit, and testable. No LLM calls in this module.

Run: `uv run pytest tests/unit/test_orchestrator_marketplace.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/marketplace.py tests/unit/test_orchestrator_marketplace.py
git commit -m "feat(orchestrator): add grounded marketplace search and ranking"
```

## Task 3: Register orchestrator search tool (TDD)

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Modify: `tests/unit/test_orchestrator_marketplace.py` (or add focused tool-binding assertions)

- [ ] **Step 1: Write failing test for tool registration/binding**

Add a test that builds the agent tools (or calls a new `_build_marketplace_search_tool(settings)` helper mirroring `_build_mediation_tool`) and asserts:
- tool name is `search_marketplace_products` (or chosen name; keep stable)
- parameters include expected fields (no browser/internal secrets)
- function uses configured `buyer_internal_url`/`buyer_internal_token`/timeout (mock HTTP/fetch helper)
- returns structured result with `products` grounded to mocked aggregation payload.

Run: `uv run pytest tests/unit/test_orchestrator_marketplace.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement tool in `agent.py`**

Add `FunctionTool` wrapper (async) that:
- validates/coerces args (`max_unit_price_cents` int, `limit` bounded)
- fetches aggregation via `marketplace.fetch_marketplace_products(...)`
- applies `filter_and_rank_products(...)`
- returns `shape_search_result(...)`
- handles errors as structured error payloads (do not leak tokens)

Add tool to `tools=[...]` in `build_agent`. Keep `mediate_seller_call` and all Verifund tools unchanged.

Run: `uv run pytest tests/unit/test_orchestrator_marketplace.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py tests/unit/test_orchestrator_marketplace.py
git commit -m "feat(orchestrator): expose marketplace product search tool"
```

## Task 4: Update orchestrator instructions for discovery + clarification handoff

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` (`MARKETMESH_ORCHESTRATOR_INSTRUCTION`)

- [ ] **Step 1: Add instruction block (small, test by inspection + existing orchestrator tests)**

Extend instruction to cover:
- **Product discovery:** for requests to find/search/browse products, call `search_marketplace_products` with extracted constraints (e.g. $1500 → `max_unit_price_cents=150000`). Use grounded results only.
- **Card context:** after tool results render, if user asks to negotiate for a shown product, confirm product/SKU/offer context from the user message.
- **Clarification checklist before starting negotiation:** quantity (default 1), user-stated budget ceiling/target, delivery deadline, warranty, returns, must-haves/preferences. Ask only for missing/ambiguous fields; be concise.
- **Confirmed brief:** once confirmed, continue the existing MarketMesh negotiation workflow in the same thread by sending/using the confirmed structured brief per the system’s run flow. Do not create ad hoc award/order outcomes.
- **Non-negotiables preserved:** never reveal/estimate buyer budget to sellers; keep mediated seller calls sequential; require `request_award_approval` before order; preserve Verifund rules.

Run: `uv run pytest tests/unit/test_orchestrator_mediation.py tests/unit/test_orchestrator_server.py -v`
Expected: PASS (no behavior regressions from instruction text; tool bindings unchanged).

- [ ] **Step 2: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py
git commit -m "feat(orchestrator): guide chat product discovery and negotiation clarification"
```

## Task 5: Console chat renders product cards and negotiate intent (v2 hooks)

**Files:**
- Create: `apps/console/features/chat/product-cards.tsx`
- Modify: `apps/console/features/chat/chat.tsx`
- Modify if needed: `apps/console/lib/types.ts`

- [ ] **Step 1: Implement card renderer component**

Create `product-cards.tsx`:
- Type the tool result (minimal fields needed; tolerate extra fields).
- Render a compact list/grid of cards with Q5 content: title, image/emoji+color, price/range+currency, availability summary, key attributes, source/merchant/offers summary.
- `View details/source`: expand inline or link using data present in result (no N+1; no external checkout).
- `Ask agent to negotiate`: button component uses `useAgent({agentId:"marketmesh_orchestrator"})` and `useCopilotKit()`; on click builds grounded intent text and dispatches in-thread:
  ```ts
  agent.addMessage({ id: crypto.randomUUID(), role: "user", content: intent });
  await copilotkit.runAgent({ agent });
  ```
  Disable while agent running if state is available; handle errors with a small inline message.
- Keep styling compatible with existing `mm-*` classes.

- [ ] **Step 2: Wire `useRenderTool` in `chat.tsx`**

Import and register:
```ts
useRenderTool({
  name: "search_marketplace_products",
  parameters: z.object({}).passthrough().optional(),
  render: ({ status, result }) => <ProductSearchCards status={status} result={result} />,
});
```
(Adjust parameters schema to what CopilotKit v1.79/v2 expects; keep permissive for structured JSON results.)

- [ ] **Step 3: Verify console types/lint/build**

Run from `apps/console` (use the project’s package manager; repo has `pnpm-lock.yaml`):
```bash
cd apps/console && pnpm typecheck
```
Expected: PASS. If `pnpm` is not used locally, use the equivalent npm command configured in package.json (`npm run typecheck`) after deps are present.

- [ ] **Step 4: Commit**

```bash
git add apps/console/features/chat/product-cards.tsx apps/console/features/chat/chat.tsx apps/console/lib/types.ts
git commit -m "feat(console): render marketplace product cards in chat"
```

## Task 6: Run initiation verification and regression pass

**Files:**
- Verify: `apps/console/features/deal-room/hooks/use-run-detail.ts` (no breaking changes)
- Verify: `apps/console/features/deal-room/run-detail.tsx`, `apps/console/app/(console)/agents/[runId]/page.tsx`
- Verify: `apps/console/app/(console)/marketplace/page.tsx`

- [ ] **Step 1: Trace/verify Q9 paths**

Confirm with code reading/manual check:
- `/marketplace` still sets `marketmesh:pendingBrief` and navigates (unchanged).
- `useRunDetail` still consumes pending brief once per route run and clears after successful dispatch.
- In an existing chat thread, negotiate intent message reaches orchestrator and clarification proceeds without leaving chat.
- Confirmed brief continues existing negotiation workflow (orchestrator mediates buyer/seller; award reaches `request_award_approval` HITL as before).

If a gap is found (e.g., confirmed brief does not trigger run in current thread context), implement the smallest fix that reuses existing `startRun`/thread semantics and document it in the plan commit message.

- [ ] **Step 2: Run targeted automated checks**

```bash
uv run pytest tests/unit/test_buyer_marketplace_auth.py tests/unit/test_orchestrator_marketplace.py tests/unit/test_orchestrator_mediation.py -v
cd apps/console && pnpm typecheck
```
Expected: PASS.

- [ ] **Step 3: Commit verification/fixes (if any)**

```bash
git add -A
git commit -m "fix: align chat discovery negotiation handoff with existing run flow"
```
(Only if Task 6 produced changes; otherwise skip.)

## Task 7: Final verification report

- [ ] **Step 1: Manual smoke checklist (document in PR/notes)**

1. Start stack (per project runbook) with console + orchestrator + buyer + registry + sellers.
2. In chat, send: `Find me a good laptop for programming under $1500`.
3. Verify product cards render in chat (grounded to MarketMesh catalog; no invented products).
4. Click `Ask agent to negotiate` on a card; verify same-thread clarification questions.
5. Provide mandate fields and confirm; verify negotiation proceeds and `request_award_approval` appears before order.
6. Verify `/marketplace` “Ask agent to negotiate” still works.

- [ ] **Step 2: Summarize evidence**

Report: tests run, typecheck result, files changed, known limitations (Q13 detail depth, subjective ranking heuristics, run-initiation path chosen), and any follow-ups.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-07-chat-product-discovery-negotiation.md`.

**Spec (approved in chat):** `docs/superpowers/specs/2026-11-07-chat-product-discovery-negotiation-design.md`

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration in this session (`superpowers:subagent-driven-development`).
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans` with checkpoints.

Which approach? Reply `1` for Subagent-Driven or `2` for Inline Execution.
