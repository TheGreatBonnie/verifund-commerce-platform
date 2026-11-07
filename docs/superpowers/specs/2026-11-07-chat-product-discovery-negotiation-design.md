# Chat Product Discovery & Negotiation Handoff (MarketMesh)

**Date:** 2026-11-07  
**Status:** Approved in chat; revised 2026-11-07 after implementation review (R1–R7).  
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

## Revision decisions (R1–R7)

These settle the open questions raised during the implementation review.

| R | Decision |
|---|---|
| R1 | Discovery matching is **local and deterministic**, with an explicit synonym/attribute map. The orchestrator does **not** forward generic query terms as registry `q`; it fetches aggregation (optionally by `category`) and matches locally. |
| R2 | The buyer marketplace endpoint **already accepts** the internal token (commit `ce78205`). The auth task is **regression coverage only**; no re-implementation. |
| R3 | Update **both** instruction surfaces: the ADK `MARKETMESH_ORCHESTRATOR_INSTRUCTION` and the CopilotKit middleware `instructions` in `apps/console/app/api/copilotkit/[[...slug]]/route.ts`. `ag_ui_adk` appends the middleware `SystemMessage` after the ADK instruction, so both reach the model. |
| R4 | A confirmed brief starts a run through the existing middleware tool `send_message_to_a2a_agent` with `agentName="MarketMesh Buyer"`. Product discovery must use `search_marketplace_products`, never the buyer. |
| R5 | The negotiate action keeps the **current chat thread**. The buyer creates a new run under the existing A2A `contextId`; the console route does not change. |
| R6 | The orchestrator uses the existing `x-verifund-internal-token` for the catalog read. This is documented as a **broad service credential** (it also authorizes run/trace/settlement internals), not least privilege. |
| R7 | Console verification includes vitest coverage for renderer registration, string-result parsing/render, and negotiate dispatch. |

## Architecture

### Discovery data path

- Buyer exposes marketplace aggregation: `GET /api/marketplace/products` in `apps/buyer_agent/buyer_agent/console_api.py`, backed by `registry_client.marketplace_products()` in `registry_client.py`. Aggregation queries registry `/v1/products` and refreshes sellers’ public `/api/catalog` for live availability/pricing.
- **Auth is already dual-token** (as of commit `ce78205`): the endpoint accepts either `x-marketmesh-console-token` (console) or `x-verifund-internal-token` (service). No change is required; a regression test pins the behavior.
- Registry `q` filtering is a substring match over `name, sku, description, category, seller_name`. The current catalog has no "laptop" vocabulary (`MacBook Air M4 13-inch` is described as `Apple M4 · 16GB memory · 256GB SSD · Space Gray`), so forwarding `q=laptop` would return zero rows.
- Therefore the orchestrator calls the buyer aggregation with `category` only when supplied, then applies **local deterministic matching** over the returned products:
  - fields: `name`, `description`, `category`, seller names, plus offer/price signals;
  - tokens expanded through a small, tested synonym/attribute table, e.g. `laptop -> macbook, notebook`, `programming -> memory, ssd, cpu, m4`.
- Sellers expose public `GET /api/catalog` (`apps/seller_agent/seller_agent/server.py`). Aggregation groups listings by SKU, sorts offers (available first, then price) and sets `unit_price_cents` / `seller` from the best offer.

### Search tool contract

Tool name: `search_marketplace_products` (stable; used by the renderer and instruction).

Input (LLM-selected, grounded):

- `query?: string`
- `category?: string`
- `max_unit_price_cents?: int`
- `in_stock_only?: bool`
- `use_case?: string` (grounded ranking hints only)
- `preferences?: string[]`
- `limit?: int` (clamped 1–24, default 12)

Output (JSON, grounded):

- `applied_filters` (echo of the effective filters)
- `total_candidates`: count **after hard filters and before `limit`**
- `products[]` with stable IDs from aggregation:
  - `id`, `sku`, `name`, `category`, `description`, `image_emoji`, `color`
  - `unit_price_cents`, `original_unit_price_cents`, `currency` (product-level, derived from `offers[0].currency`, default `USD`)
  - `rating`, `reviews`
  - availability summary (`offers[]` with seller, price, currency, available, on_hand, incoming)
  - `seller` / merchant name
  - `source="marketmesh_registry"`
  - optional deterministic `match_rationale` (list of matched tokens/fields; never free-form claims)
- On upstream failure: structured `{"error": "marketplace_unavailable", "message": ...}` without tokens or internal URLs.

### Matching, ranking, filtering (Q8, R1)

**Tokenization:** casefold, strip punctuation, split on whitespace; drop one-character tokens; expand each token through the synonym table.

**Hard filters (deterministic):**

- `query` tokens: at least one expanded token must appear in the product haystack (name/description/category/seller names).
- `category`: case-insensitive equality when supplied.
- `max_unit_price_cents`: `unit_price_cents <= ceiling`.
- `in_stock_only`: at least one offer with `available == true`.

**Scoring (deterministic, integer weights, grounded):**

- `+4` per query token matched in `name`
- `+2` per query token matched in `description` or `category`
- `+1` per `use_case`/`preferences` token matched in any field
- `+2` when any offer is available
- `+1` when `rating >= 4.5`
- `+1` when `original_unit_price_cents` is present and greater than `unit_price_cents`

**Ordering:** `(-score, unit_price_cents, sku)`. No floats, so ordering is stable across runs and Python versions.

**LLM role:** extract constraints and choose tool args; summarize using returned fields only. Never add products that aggregation did not return.

### Console chat rendering (Q11, R7)

- Register `useRenderTool` for `search_marketplace_products` in `apps/console/features/chat/chat.tsx`; the card UI lives in `apps/console/features/chat/product-cards.tsx`.
- **Tool results may arrive as a JSON string** (backend function tools) or as an object. Normalize with the existing string-or-object pattern (`parseVerifundToolResult`) before rendering; never assume `result.products` exists.
- Render cards with Q5 content and only these actions: **Ask agent to negotiate** and **View details/source**.
- `View details/source` expands from result data (offers, availability, seller, description). No N+1 refresh in this change.
- Empty result: render a compact "No matching products" state rather than nothing.
- Currency: `product.currency ?? offers[0].currency ?? "USD"`.

### Negotiate button (Q12, R5, R7)

- Sends a **user intent message in the same thread** via CopilotKit v2 hooks available in the app: `useAgent({agentId:"marketmesh_orchestrator"})` + `useCopilotKit()` → `agent.addMessage(...)` + `copilotkit.runAgent({agent})` (consistent with `apps/console/features/deal-room/hooks/use-run-detail.ts`).
- Intent message includes grounded product context (SKU, name, unit price, offers) and requests mandate clarification.
- Local `isDispatching` guard disables the button while the run is in flight; dispatch errors render inline on the card.
- No direct order/seller/order endpoint calls and no navigation.

### Clarification and run initiation (Q4, Q9, R4)

- Orchestrator collects/confirms: quantity (default 1), user-stated budget ceiling/target, delivery deadline, warranty, returns, preferences/must-haves.
- Ask only for fields that are **missing or ambiguous**. Do not interrogate a brief that already states them (the existing sample brief and direct chat briefs stay one-shot).
- Confirmed brief continues the **existing MarketMesh negotiation workflow** in the same thread:
  - the orchestrator calls `send_message_to_a2a_agent` with `agentName="MarketMesh Buyer"` and a `task` containing the confirmed mandate plus grounded product context;
  - the buyer treats a non-approval message as a new sourcing brief and creates a new run under the thread's `contextId`;
  - the console route stays on the current page; the chat and thread-level HITL cards continue in place.
- Implementation must keep `marketmesh:pendingBrief` consumption in `use-run-detail.ts` working for `/marketplace` entry flows.
- **Never reveal/estimate buyer budget to sellers.** Budget stays in the buyer mandate.

### Safety

- No hallucinated products; cards map only to aggregation results.
- Existing HITL approvals remain mandatory (`request_award_approval`, Verifund approvals), and the award HITL remains a thread-level frontend tool.
- No secrets/tokens in the browser. The orchestrator's internal token is a broad service credential (R6); do not expose it to the client or tool output.
- Discovery never places orders or starts settlement; only negotiation/brief flow.

## Verification during implementation

1. Both instruction surfaces mention discovery (`search_marketplace_products`) and the buyer handoff (`send_message_to_a2a_agent` + `MarketMesh Buyer`).
2. Same-thread confirmed brief creates a new buyer run and preserves `request_award_approval`; `/marketplace` `pendingBrief` entry unchanged.
3. Buyer marketplace auth regression: console token and internal token both accepted; invalid/missing rejected.
4. Console vitest: renderer registration, string-result parsing/render, negotiate `addMessage` + `runAgent` dispatch.
5. Matching test uses the literal prompt "good laptop for programming under $1500" and returns the MacBook Air grounded to aggregation data.

## Out of scope / follow-ups

- Multi-select compare, cart/checkout, UCP storefront integration.
- Per-user locale/currency/shipping context (currency remains offer-derived, USD in the demo).
- Catalog vocabulary/tags migration (R1 keeps the synonym table inside the orchestrator module for now).
- Rich image CDN if catalog lacks images (use emoji/color fields; extensible).
