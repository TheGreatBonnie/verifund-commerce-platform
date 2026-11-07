# Chat Product Discovery & Negotiation Handoff (MarketMesh)

**Date:** 2026-11-07  
**Status:** Approved in chat (user: "Approved. proceed to implementation planning")  
**Scope:** `verifund-a2a` console chat (CopilotKit v1.79 / `@copilotkit/react-core`), `marketmesh_orchestrator` (ADK/AG-UI, Python), buyer/registry marketplace aggregation.

## Goal

Enable a chat prompt such as:

> "Find me a good laptop for programming under $1500"

to:

1. Discover products from **MarketMesh sellers/registry** (not an external UCP storefront).
2. Render **product cards in the CopilotKit chat message stream**.
3. Let the user click **"Ask agent to negotiate"** to **clarify a purchase mandate in chat, then start the existing MarketMesh negotiation workflow in the same thread/context**. The existing negotiation safety/workflow is preserved (registry sellers, RFQ/counter, deterministic award, `request_award_approval` HITL, order/settlement after approval).

## Non-goals

- No external UCP agent profile, MCP storefront, cart, or checkout from product cards.
- No replacement of award/approval/order/settlement logic.
- No navigation away from chat required for the clarification flow (Q9). Existing marketplace page behavior (`marketmesh:pendingBrief` + navigation) remains unchanged unless explicitly refactored.

## Decisions (Q1–Q13)

| Q | Decision |
|---|---|
| Q1 | Catalog/source = **MarketMesh sellers/registry**. Map `search_catalog -> get_product/lookup_catalog` concept to internal aggregation/seller catalogs. |
| Q2 | Discovery logic runs in **agent/orchestrator layer**. |
| Q3 | Products displayed as **product cards in chat**. |
| Q4 | “Ask agent to negotiate” = **clarify mandate in chat, then start MarketMesh run** in the same thread. |
| Q5 | Cards: title, image/emoji, price/range+currency, variant/availability summary, key attributes, source/merchant. Actions: **Ask agent to negotiate + View details/source** only. |
| Q6/Q10 | No external UCP profile. **Reuse existing buyer/registry/console/internal config**; USD/demo defaults; extensible interfaces. |
| Q7 | **Orchestrator tool wraps marketplace aggregation** (reuse buyer/registry marketplace logic). |
| Q8 | **LLM extracts constraints + deterministic filter/rank**; candidates grounded to returned catalog IDs/SKUs (no hallucinated products). Subjective intent ("good for programming") handled via grounded heuristics/rationale. |
| Q9 | **Collect fields in chat, send confirmed brief in same thread**. |
| Q11 | **New orchestrator tool + `useRenderTool`** product cards in console chat. |
| Q12 | Button **sends a user message/intent via CopilotKit** to trigger clarification/negotiation in-thread. |
| Q13 | **Use aggregation data + optional targeted refresh** for detail (avoid N+1). |

## Architecture

### Discovery data path

- Buyer exposes marketplace aggregation: `GET /api/marketplace/products` in `apps/buyer_agent/buyer_agent/console_api.py` (currently `x-marketmesh-console-token`) backed by `registry_client.marketplace_products()` in `registry_client.py`. Aggregation queries registry `/v1/products` and refreshes sellers’ public `/api/catalog` for live availability/pricing.
- Sellers expose public `GET /api/catalog` (`apps/seller_agent/seller_agent/server.py`).
- Orchestrator adds `search_marketplace_products` (name stable in implementation) that calls buyer marketplace aggregation over HTTP (service boundary preserved) and applies deterministic filtering/ranking. **Auth:** allow orchestrator internal access without exposing secrets to browser (minimal backward-compatible approach: accept `x-verifund-internal-token` for marketplace endpoint in addition to existing console token).

### Search tool contract (proposed)

Input (LLM-selected, grounded):
- `query?: string`
- `category?: string`
- `max_unit_price_cents?: int`
- `in_stock_only?: bool`
- `use_case?: string` (grounded ranking hints only)
- `preferences?: string[]`
- `limit?: int`

Output (JSON, grounded): `applied_filters`, `total_candidates`, `products[]` with stable IDs from aggregation, `name`, `category`, `description`, `image_emoji`/`color`, `unit_price_cents`/range, `currency`, availability summary, key attributes when available, `offers[]`, `source="marketmesh_registry"`, optional grounded `match_rationale`.

### Ranking/filtering (Q8)

- **Hard filters (deterministic):** query/category text match, `max_unit_price_cents`, availability.
- **Scoring (deterministic, grounded):** relevance from query/use_case/preferences against returned fields; rating/availability/value signals. Never add products not returned by aggregation.
- **LLM role:** extract constraints and choose tool args; summarize rationale using returned fields only.

### Console chat rendering (Q11)

- Register `useRenderTool` for the marketplace search tool in `apps/console/features/chat/chat.tsx` (or extracted module).
- Render cards inline: Q5 content + `Ask agent to negotiate` and `View details/source` only.
- “View details/source” uses result data first (Q13); optional targeted refresh/detail only if required.

### Negotiate button (Q12)

- Sends a **user intent message in the same thread** via CopilotKit v2 hooks available in app: `useAgent({agentId:"marketmesh_orchestrator"})` + `useCopilotKit()` → `agent.addMessage(...)` + `copilotkit.runAgent({agent})` (consistent with `apps/console/features/deal-room/hooks/use-run-detail.ts`).
- Intent message includes grounded product context and requests mandate clarification.
- No direct order/seller/order endpoint calls from the button.

### Clarification and run initiation (Q4, Q9)

- Orchestrator collects/confirms: quantity, user-stated budget ceiling/target, delivery deadline, warranty, returns, preferences/must-haves. **Never reveal/estimate buyer budget to sellers.**
- Confirmed brief continues the **existing MarketMesh negotiation workflow** in the same thread/context.
- Implementation must verify and reuse actual run initiation behavior: `useRunDetail.startRun()` (message + `runAgent`), `threadId` handling, and `marketmesh:pendingBrief` consumption in `apps/console/features/deal-room/hooks/use-run-detail.ts` for agent/run entry flows. Do not regress existing behavior.

### Safety

- No hallucinated products; cards map to aggregation results.
- Existing HITL approvals remain mandatory (`request_award_approval`, Verifund approvals).
- No secrets/tokens in browser.

## Verification during implementation

1. CopilotKit v1.79 `@copilotkit/react-core/v2` message dispatch from a rendered tool component.
2. Same-thread confirmed brief → existing negotiation/run path; `pendingBrief`/`startRun` compatibility.
3. Buyer marketplace auth for orchestrator (internal token, minimal scope) with tests.

## Out of scope / follow-ups

- Multi-select compare, cart/checkout, UCP storefront integration.
- Per-user locale/currency/shipping context.
- Rich image CDN if catalog lacks images (use emoji/color fields; extensible).
