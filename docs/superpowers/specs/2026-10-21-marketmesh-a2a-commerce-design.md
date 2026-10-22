# MarketMesh — A2A Commerce Exchange Design

**Date:** 2026-10-21  
**Status:** Approved design, pending spec review  
**Scope:** Standalone, local-first production prototype in `verifund-a2a/`

## 1. Purpose

MarketMesh is an open agent-to-agent commerce exchange in which independently operated buyer and seller agents discover one another, exchange structured requests, negotiate prices, compare offers, pause for human approval, and coordinate orders.

The project must be completely standalone. It must not import, call, depend on, or reproduce Verifund or any Verifund-related service, code, payment workflow, transaction coordinator, data model, or dependency. User-facing branding is MarketMesh. The required directory name remains `verifund-a2a/`.

The demo is not a pair of chatbots. Buyer-to-seller commerce is carried over Google's A2A protocol with real tasks, artifacts, status transitions, streaming updates, cancellation, and idempotent order handling. A web console makes the protocol and negotiation visible.

## 2. Goals

- Demonstrate real A2A interoperability between independently hosted agents.
- Support discovery through a registry of validated Agent Cards.
- Exchange machine-readable RFQs, offers, counteroffers, approvals, and orders.
- Run genuine multi-round price negotiation with seller-specific policies.
- Compare offers with deterministic, auditable scoring.
- Require explicit human approval before every order.
- Show the full interaction in a CopilotKit console, including raw A2A frames.
- Provide a local-first production prototype: persistence, auth, retries, timeouts, idempotency, tests, Docker Compose, and operational docs.
- Remain fully usable without Verifund or any Verifund-adjacent runtime.

## 3. Non-goals

- Payment processing, payment authorization, escrow, or a transaction coordinator.
- Real fulfillment, shipping, carrier integration, or inventory synchronization.
- Multi-tenant identity, hosted registry, or cloud deployment automation.
- Push-notification webhooks.
- Cryptographically verifiable cross-organization approval attestation.
- Horizontal scaling, distributed task stores, or queue infrastructure.
- Replacing A2A with a custom agent protocol.

## 4. Fixed decisions

| Decision | Choice |
|---|---|
| Product name | MarketMesh |
| Commerce scenario | Buyer purchasing 12 noise-cancelling headsets |
| Agent framework | LangGraph for buyer and all sellers |
| LLM access | Nebius token factory, model `deepseek-ai/DeepSeek-V4-Flash-0731` by default |
| Agent intelligence | LLM-first, bounded by deterministic tools and validators |
| Human authority | Human approves every order; no auto-approval |
| Discovery | Agent Card registry plus direct Card validation by buyer |
| UI ↔ buyer | AG-UI via CopilotKit + `ag-ui-langgraph` |
| Buyer ↔ seller | A2A 1.x JSON-RPC over HTTP with SSE streaming |
| Frontend | Existing Next.js 15 + CopilotKit 1.79 codebase, rewritten for commerce |
| Persistence | SQLite in WAL mode, separate database per service |
| Auth | Per-seller bearer tokens; admin token for registry writes |
| Deployment | Local dev commands and Docker Compose |

## 5. Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│ Next.js 15 + CopilotKit console            localhost:3000   │
│ chat · deal room · A2A wire · approval card                  │
└───────────────────────────┬──────────────────────────────────┘
                            │ AG-UI (streaming + interrupts)
┌───────────────────────────▼──────────────────────────────────┐
│ Buyer Agent                                 localhost:9100   │
│ LangGraph · mandate · scoring · approval · trace · SQLite    │
│ AG-UI endpoint + read-only console API                       │
└───────────────┬───────────────────────────────┬──────────────┘
                │ REST discovery                │ A2A 1.x JSON-RPC + SSE
┌───────────────▼──────────────┐   ┌────────────▼───────────────┐
│ Registry        :9105        │   │ Northwind Audio   :9201    │
│ Agent Card index · health    │   │ CircuitForge      :9202    │
│ no catalog · no inventory    │   │ Aurora Supply     :9203    │
└──────────────────────────────┘   │ LangGraph · own SQLite      │
                                   │ catalog · inventory · policy│
                                   │ offers · orders · checkpoints│
                                   └────────────────────────────┘
```

### 5.1 Service responsibilities

| Component | Owns | Must not own |
|---|---|---|
| Console | Presentation, chat, live deal room, A2A inspector, approval interaction | Negotiation logic, catalog, order state |
| Buyer | Mandate, discovery, RFQ fan-out, negotiation strategy, scoring, approval interrupt, trace | Seller prices, inventory, fulfillment |
| Seller | Catalog, inventory, pricing floor and policy, offers, order creation, task checkpoints | Buyer budget, other sellers, cross-seller ranking |
| Registry | Agent Card snapshots, categories, Card validation, health | Products, prices, inventory, orders |
| Shared core | Contracts, A2A extension helpers, money, pricing primitives, scoring, tracing | Per-service runtime state |

### 5.2 Independence

Each seller runs as a separate process with:

- its own port, bearer token, database, catalog, pricing policy, prompt configuration, and Agent Card;
- no shared mutable database with the buyer, registry, or other sellers;
- no knowledge of other sellers or the buyer's maximum budget.

The three sellers share the seller runtime package to keep the prototype maintainable. This is a code-sharing convenience, not a protocol assumption. A production deployment could replace any seller with an independently built A2A-compatible service without changing the buyer.

### 5.3 Stack

- Python 3.12, FastAPI, Uvicorn, Pydantic 2.
- `a2a-sdk==1.2.3` with HTTP server and SQLite extras.
- LangGraph 1.2.x, `langgraph-checkpoint-sqlite`.
- `ag-ui-langgraph==0.0.47`, `ag-ui-protocol`.
- `langchain-openai` pointed at Nebius's OpenAI-compatible endpoint.
- SQLAlchemy 2 async + `aiosqlite`.
- Next.js 15.5, React 19, CopilotKit 1.79, Tailwind 4.
- Pytest, HTTPX, Playwright.
- Docker Compose.

The three A2A seller services use the current 1.x protocol. The legacy `@ag-ui/a2a-middleware` is removed because it flattens A2A to one-shot text and cannot represent tasks, artifacts, streaming, or `input-required`.

## 6. Repository layout

```text
verifund-a2a/
  apps/
    console/                     # Next.js + CopilotKit
      app/
      components/
      lib/
    buyer_agent/
      buyer_agent/
        graph.py
        a2a_client.py
        console_api.py
        approval.py
        settings.py
    seller_agent/
      seller_agent/
        graph.py
        executor.py
        policy.py
        catalog.py
        order_service.py
      profiles/
        northwind.yaml
        circuitforge.yaml
        aurora.yaml
    registry/
      registry/
        api.py
        card_validator.py
        store.py
  packages/
    commerce_core/
      commerce_core/
        contracts.py
        extension.py
        money.py
        pricing.py
        scoring.py
        a2a_parts.py
        tracing.py
        logging.py
  data/                          # gitignored SQLite files
  docs/
  scripts/
    dev.py
    seed.py
    run_demo.py
    export_schemas.py
  tests/
    unit/
    protocol/
    integration/
    e2e/
  docker-compose.yml
  Makefile
  pyproject.toml
  README.md
```

## 7. A2A protocol layer

### 7.1 Wire baseline

- A2A 1.x via `a2a-sdk 1.2.3`.
- JSON-RPC 2.0 binding over HTTP.
- SSE streaming for task status and artifact updates.
- Agent Card at `GET /.well-known/agent-card.json`.
- RPC endpoint at `POST /a2a`.
- Supported operations: `message/send`, `message/stream`, `tasks/get`, `tasks/list`, `tasks/cancel`.
- No gRPC, no REST binding, no push notifications.
- Auth: HTTP bearer declared in each Agent Card.

### 7.2 Agent Card

Each seller Card declares:

- name, description, version, provider, documentation URL;
- `protocolVersion` matching the SDK's current 1.x version;
- preferred transport `JSONRPC`;
- streaming capability true;
- push notifications false;
- input mode `application/json` and `text/plain`;
- output mode `application/json`;
- skills: `commerce.catalog.search`, `commerce.quote`, `commerce.negotiate`, `commerce.order`;
- required extension `https://marketmesh.example/extensions/commerce/v1`;
- bearer security scheme;
- seller profile metadata: categories, regions, sustainability, rating.

The registry fetches Cards from the well-known URL. The buyer re-fetches Cards directly and validates protocol version, extension, skills, auth scheme, and reachability before sending an RFQ.

### 7.3 Commerce extension

Extension URI: `https://marketmesh.example/extensions/commerce/v1`. The `.example` domain is deliberately reserved and is not owned or dereferenced at runtime.

Structured payloads travel as A2A DataParts with a common envelope:

```json
{
  "schema": "https://marketmesh.example/extensions/commerce/v1/rfq.json",
  "schema_version": "1.0",
  "payload": {}
}
```

Artifacts are named `offer`, `order`, or `commerce-error`. Human-readable prose never carries authoritative values. All money is integer cents with ISO-4217 currency. All timestamps are RFC 3339 UTC. IDs are UUIDv4 or ULID.

### 7.4 Core contracts

#### ShoppingBrief / Mandate

- `run_id`, `buyer_id`, `currency`
- `quantity`
- `max_total_cents`
- `deadline_days`
- `min_warranty_months`
- `min_returns_days`
- `preferences`: sustainability, color, brand exclusions
- `approval_required` always true

The maximum total is buyer-side only and is never sent to sellers.

#### RFQ

- `request_id`, `run_id`, `category`, `product_hint`
- `quantity`, `required_by`
- `constraints`: warranty, returns, color
- `preferences`: sustainability, delivery preference
- `message`: optional human context

#### Offer

- `offer_id`, `request_id`, `seller_id`, `seller_name`
- `currency`
- `line_items`: SKU, name, quantity, unit price cents, list unit price cents, warranty add-on, attributes
- `subtotal_cents`, `shipping_cents`, `total_cents`
- `delivery_days`, `delivery_date`
- `warranty_months`, `returns_days`
- `valid_until`
- `terms`: sustainability certification, stock confidence, split-shipment details
- `status`: `proposed`, `final`, `accepted`, `rejected`
- `round`
- `rationale`

Totals are recomputed and validated by the seller; client-supplied totals are never trusted.

#### CounterOffer

- `negotiation_round`
- `target_unit_price_cents`
- `requested_changes`: field/value pairs, such as warranty or delivery
- `rationale`

#### AcceptOffer

- `offer_id`, `round`, `accepted_total_cents`, `accepted_by_buyer_task`

#### PurchaseOrderRequest

- `request_id`, `run_id`, `offer_id`, `seller_id`
- `quantity`
- `shipping_address`
- `approval`: approval id, approver label, timestamp, note
- `idempotency_key`
- `expected_total_cents`

#### Order

- `order_id`, `offer_id`, `seller_id`
- `status`
- `currency`, `quantity`, `total_cents`
- `line_items`
- `reserved_at`, `eta`, `tracking_number`
- `fulfillment`: mock carrier and status

#### CommerceError

- `code`: `out_of_stock`, `offer_expired`, `below_floor`, `invalid_request`, `unsupported_constraint`, `conflict`
- `message`
- `retryable`
- `details`

## 8. Task lifecycle

### 8.1 Negotiation task

1. Buyer generates a `contextId` for the run and sends an RFQ over `message/stream` to each discovered seller. Each seller gets its own `taskId`.
2. Seller task moves `submitted → working`, emits progress updates, searches its catalog, checks inventory, applies policy, and emits an `offer` artifact.
3. Seller moves the task to `input-required`, inviting a counteroffer.
4. Buyer sends a `CounterOffer` DataPart with the same `taskId` and `contextId`.
5. Seller resumes, validates the counter against its allowed concession ladder, and responds with a new offer, a rejection, or acceptance. Maximum three negotiation rounds.
6. Final offers remain `input-required` while the buyer compares all sellers and waits for human approval.
7. After approval:
   - buyer sends `AcceptOffer` to the winner's negotiation task, completing it;
   - buyer creates a separate order task with the same `contextId` and `reference_task_ids=[negotiation_task_id]`;
   - buyer cancels losing negotiation tasks with `tasks/cancel`.
8. If the human rejects, buyer cancels all open negotiation tasks and completes the run without an order.

### 8.2 Order task

1. Buyer creates an order task containing `PurchaseOrderRequest`.
2. Seller verifies the referenced offer, validity, stock, expected total, and required approval receipt presence.
3. Seller reserves inventory in a single SQLite transaction and creates the order idempotently.
4. Seller emits the `order` artifact and completes the task.
5. Duplicate submissions with the same idempotency key return the original order instead of reserving twice.

### 8.3 Approval boundary

Human approval is not an A2A task state. It is a buyer LangGraph interrupt surfaced through AG-UI. No seller is contacted between the approval request and the human decision. The seller receives the approval receipt in the order task as an assertion; it cannot cryptographically verify a cross-organization approval.

### 8.4 Discovery flow

1. Buyer queries registry `POST /v1/discover` with category and required extension.
2. Registry returns seller IDs, Agent Card URLs, snapshot hashes, and last-seen timestamps.
3. Buyer fetches each Card directly from the seller's well-known endpoint.
4. Buyer validates the Card and records latency. Invalid Cards are excluded with a trace event.
5. The registry is never a commerce proxy.

## 9. Agent design

### 9.1 Scenario

Buyer needs 12 Nimbus NC-700 ANC headsets in black:

- total budget: $3,400;
- delivery within 14 days;
- warranty at least 24 months;
- returns at least 30 days;
- sustainability preferred but not required;
- human approval required.

### 9.2 Seller profiles

| Seller | Profile | Initial offer | Negotiated outcome |
|---|---|---|---|
| Northwind Audio | Premium; 36-month warranty, 3-day delivery, rating 4.8, sustainable | $303.05/unit, $3,636.60 | $281.00/unit, $3,372.00 |
| CircuitForge | Value; 12-month base warranty, 7-day delivery, rating 4.4 | $263.12/unit, $3,157.44 but warranty fails | Adds 24-month extended warranty; $269.12/unit, $3,229.44 |
| Aurora Supply | Balanced; 24-month warranty, 5-day delivery, rating 4.6, sustainable; 8 in stock | $309.00/unit, $3,708.00 but quantity fails | Sources restock, split shipment in 10 days; $283.33/unit, $3,399.96 |

The buyer never sees seller floors. The seller never sees the buyer's maximum budget. Outcomes are produced by bounded policy ladders, not hardcoded buyer decisions.

### 9.3 Buyer graph

1. `interpret_brief`: LLM converts the chat brief into `ShoppingBrief`; deterministic validation asks for missing budget, quantity, or constraints.
2. `discover_sellers`: registry query, direct Card fetch, validation.
3. `plan_sourcing`: LLM chooses RFQ wording and seller coverage; mandate and category are fixed.
4. `issue_rfqs`: parallel A2A `message/stream` calls.
5. `evaluate_offers`: deterministic eligibility and scoring; LLM writes an explanation.
6. `negotiate_sellers`: LangGraph `Send` fan-out to one negotiation subgraph per seller, maximum three rounds.
7. `rank_offers`: deterministic score, tie-breaks, award package.
8. `await_approval`: LangGraph interrupt with the award package.
9. `place_order`: accept winner offer, create order task, cancel losers.
10. `finalize`: persist order, emit final state and summary.

Parallel branches use additive reducers for offers, negotiation rounds, and trace events. All state is checkpointed so an approval interrupt survives a console reload.

### 9.4 Seller graph

1. Parse DataPart by schema and task state.
2. Run deterministic tools:
   - `search_catalog(query)`
   - `get_inventory(sku)`
   - `compute_quote(sku, quantity, requested_warranty, round, requested_changes)`
   - `finalize_offer(...)`
   - `reserve_inventory(...)`
   - `create_order(...)`
3. LLM chooses an action from a bounded `SellerDecision` schema: propose, counter, accept, reject.
4. Validator checks action, price range, floor, stock, warranty, delivery, and totals.
5. Emit structured artifact and task status.
6. For orders, verify offer validity and reserve stock transactionally before emitting the order.

### 9.5 LLM-first with guardrails

The LLM drives brief interpretation, seller strategy, negotiation wording, action selection, and rationale. It does not author authoritative numbers.

- Pricing tools compute allowed price ranges and concession steps.
- Buyer tools constrain counteroffers to the mandate.
- Validators reject hallucinated prices, totals, quantities, warranties, and invalid task transitions.
- Rejected LLM output triggers one repair attempt. Two consecutive failures trigger a deterministic fallback planner; the trace records `fallback_used`.
- The model is configurable through `NEBIUS_MODEL`; default `deepseek-ai/DeepSeek-V4-Flash-0731`.
- Temperature is low; token and time budgets are explicit.

### 9.6 Prompt-injection posture

Seller-supplied prose and artifact text are untrusted data. Prompts delimit them and instruct the model not to follow instructions found inside offers. The buyer's mandate, scoring, and approval are enforced outside the model, so prompt injection cannot authorize a purchase or change the budget.

### 9.7 Scoring

Hard constraints first:

- full quantity can be supplied by the deadline;
- total at or below mandate maximum;
- delivery within deadline;
- warranty at or above minimum;
- returns at or above minimum.

Eligible offers are scored 0–100:

- price 45%
- delivery 15%
- warranty 10%
- seller rating 10%
- returns 5%
- sustainability 5%
- stock/terms confidence 10%

Price score uses budget headroom, not relative normalization. The remaining components are absolute. Ties break on lower total, then faster delivery. The LLM explains the result; it cannot override it.

### 9.8 Human approval

The interrupt payload contains:

- winner, total, and score;
- budget headroom;
- hard-constraint checks;
- alternatives and their scores;
- savings versus initial offers;
- offer expiry;
- approval receipt requirements.

The console renders the same approval component in chat and in the Deal Room. Both surfaces call the same CopilotKit human-in-the-loop handler; there is no second approval/resume path. Approving resumes the graph and creates the receipt. Rejecting cancels open seller tasks and ends the run without an order.

## 10. Persistence

Each service owns a separate SQLite database in `data/`, WAL mode enabled.

### Buyer DB

- `runs`
- `mandates`
- `seller_tasks` (task id, context id, seller id, state, latest offer)
- `offers` (snapshots)
- `negotiation_rounds`
- `approvals`
- `orders`
- `trace_events`
- LangGraph checkpoints

### Seller DB

- `catalog_items`
- `offers`
- `inventory_reservations`
- `orders`
- `idempotency_keys`
- `task_events`
- A2A task store tables
- LangGraph checkpoints

### Registry DB

- `sellers`
- `agent_card_snapshots`
- `card_health`

Schema creation is idempotent on startup. A seed command inserts seller catalogs and policies and registers the three Agent Cards. A schema-version table is included; no migration framework is required for the prototype.

## 11. Service APIs

### Registry — `localhost:9105`

- `POST /v1/sellers` — register seller Card URL (admin bearer).
- `GET /v1/sellers` — list known sellers and health.
- `POST /v1/discover` — category + required extension query.
- `POST /v1/sellers/{id}/refresh` — re-fetch Card.
- `GET /health`, `GET /ready`.

### Buyer — `localhost:9100`

- `POST /agui` — AG-UI streaming endpoint for the console.
- `GET /api/runs` — recent runs.
- `GET /api/runs/{run_id}` — run summary and state.
- `GET /api/runs/{run_id}/trace` — paginated raw A2A trace, auth headers redacted.
- `GET /health`, `GET /ready`, `GET /metrics`.

### Seller — `localhost:9201–9203`

- `GET /.well-known/agent-card.json`
- `POST /a2a` — A2A JSON-RPC.
- `GET /health`, `GET /ready`, `GET /metrics`.

### Console — `localhost:3000`

- CopilotKit runtime route.
- Read-only proxy routes to buyer trace/run APIs and registry.
- No direct database access.

## 12. Console

### 12.1 Preserved CopilotKit capabilities

- CopilotKit provider and chat.
- Streaming AG-UI runs.
- State snapshots from the buyer graph.
- Generative UI for offers and approvals.
- Human-in-the-loop interrupt handling.
- Optional threads drawer and thread history, retaining the existing local/intelligence configuration.
- Existing Next.js fonts and design tokens where useful.

### 12.2 Layout

```text
┌─────────────────────────────────────────────────────────────────────┐
│ MarketMesh   ● Registry  ● 3 sellers   DeepSeek V4.1   [New run]    │
├───────────────────┬─────────────────────────────────────────────────┤
│                   │  Brief → Discover → RFQ → Negotiate → Approve    │
│  CopilotKit chat  │  → Order                                        │
│                   ├─────────────────────────────────────────────────┤
│  buyer brief      │  Deal Room | Negotiations | A2A Wire | Order     │
│  clarifications   │                                                 │
│  approval card    │  seller lanes · offer matrix · score deltas     │
│                   │  structured rounds · mandate checks             │
│  thread history   │  raw JSON-RPC frames · order/fulfillment        │
└───────────────────┴─────────────────────────────────────────────────┘
```

### 12.3 Views

- **Deal Room:** seller lanes, live offer cards, eligibility failures, comparison matrix, score bars.
- **Negotiations:** structured rounds per seller, amounts, requested changes, task states, guardrail rejections.
- **A2A Wire:** timestamp, direction, seller, method, task/context IDs, state transitions, artifact names, latency, expandable redacted JSON, filters.
- **Order:** approval receipt, winning offer, mandate checks, PO, mock fulfillment timeline and tracking.
- **Registry:** Card snapshots, protocol version, extension, skills, auth scheme, reachability, refresh time.

### 12.4 States

- Idle with sample briefs and live registry cards.
- Running with stage stepper and streaming lanes.
- Awaiting approval with mandate checks and alternatives.
- Ordered with order artifact and fulfillment.
- Partial/error with unavailable seller, expired offer, or guardrail banner.
- No static mock data; empty states are explicit.

### 12.5 Visual direction

“Editorial trading floor”: warm paper canvas, ink typography, signal green/amber/red, fine rules, monospaced protocol data. Keep Plus Jakarta Sans and Spline Sans Mono; add one editorial display face for section headings. WCAG AA contrast, keyboard approval, visible focus, reduced-motion support, responsive stacking at narrow widths.

## 13. Failure handling

| Failure | Behavior |
|---|---|
| Seller unreachable/timeout | Mark seller unavailable; continue with remaining sellers; trace the error |
| Invalid Agent Card | Exclude seller; registry health shows the problem |
| Malformed artifact | Reject artifact; mark seller degraded; optionally retry once |
| LLM invalid output | Repair once; then deterministic fallback; trace guardrail event |
| Price below floor / above mandate | Reject action; do not emit artifact; trace rejection |
| Out of stock at reservation | Return `out_of_stock`; buyer may re-negotiate or fail gracefully |
| Expired offer | Reject order with `offer_expired`; require revalidation |
| Duplicate order | Return existing order for the same idempotency key |
| Duplicate message retry | Reuse `messageId`; seller task store deduplicates |
| Console reload during approval | Resume from LangGraph checkpoint and AG-UI thread state |
| Seller returns wrong protocol version | Refuse RFQ and trace the incompatibility |

Retries use bounded exponential backoff with jitter. Transport retries reuse message IDs. Order retries require an idempotency key. All waits have explicit timeouts.

## 14. Security

- All services bind to `127.0.0.1` by default; Compose publishes to localhost only.
- Per-seller bearer tokens; registry admin token; constant-time comparisons.
- Secrets loaded from environment, never logged.
- Agent Card fetching restricted to configured local origins in the prototype; production requires an allowlist and SSRF defenses.
- Inbound body size limits and Pydantic validation.
- Authorization headers and cookies redacted from traces.
- CORS restricted to the console origin for browser-facing routes.
- Sellers validate every inbound task and state transition.
- Buyer treats seller content as untrusted; prompt injection cannot change mandate, scoring, or approval.
- Approval receipts are audit assertions, not cryptographic attestations.
- No payment data is collected, stored, or transmitted.

## 15. Observability

- Structured JSON logs with `trace_id`, `run_id`, `context_id`, `task_id`, `seller_id`, `event`, and latency.
- Persisted trace events for the console.
- `/health`, `/ready`, and `/metrics` on each service.
- Metrics: A2A requests, task state counts, negotiation rounds, LLM calls/failures, guardrail rejections, order outcomes, latency histograms.
- Raw trace payloads are bounded and redacted. Full payloads are fetched on demand by the console.

## 16. Testing

### Unit

- Money arithmetic and currency handling.
- Contract validation and schema versioning.
- Pricing policy floors, tiers, warranty add-ons, and concession ladders.
- Scoring, hard constraints, tie-breaks.
- Mandate and approval validation.
- Idempotency and trace redaction.

### Protocol

- Agent Card discovery and validation.
- RFQ `message/send` and `message/stream`.
- Offer artifact and `input-required` state.
- Counteroffer turn resuming the same task.
- AcceptOffer completion.
- Order task with reference and idempotency.
- Duplicate order submission.
- `tasks/cancel`.
- Auth rejection.
- Malformed DataPart and wrong schema version.
- Unsupported protocol version.
- Seller timeout.

### Integration

- Full buyer run against three real seller services with a scripted LLM double.
- Approve path and reject path.
- One seller unavailable.
- One seller out of stock at reservation.
- Expired offer.
- LLM repair and fallback behavior.

### End-to-end

- Playwright: start demo, see three seller lanes, observe offers and negotiation, open A2A Wire, approve, see order.
- Optional live Nebius smoke test, manual only.

### Commands

- `make test` — unit, protocol, integration.
- `make e2e` — Playwright.
- `make lint` — Python and TypeScript checks.
- `make demo` — seed and run the scripted scenario against live services.

## 17. Operations

- `make setup` installs Python and Node dependencies and creates `.env` from the example.
- `make dev` starts registry, three sellers, buyer, and console.
- `make seed` initializes catalogs, policies, and Agent Card registrations.
- `make down` stops local processes.
- `docker compose up --build` starts the same topology with health checks and a data volume.
- `data/` is gitignored and resettable with `make reset`.
- Runbook covers ports, logs, seed/reset, token rotation, common failures, and live-mode checks.

## 18. Acceptance criteria

1. `make dev` starts the console, registry, buyer, and three sellers; all Cards validate.
2. A buyer brief creates three real A2A tasks with distinct task/context IDs and structured offers.
3. At least two negotiation rounds occur; offer artifacts and task transitions are visible in the UI and raw A2A inspector.
4. No order is sent before human approval. Approve creates an order artifact; reject creates none.
5. Losing tasks are cancelled and duplicate order requests return the same order.
6. One seller can fail without aborting procurement.
7. `make test` and the Playwright smoke test pass without Nebius access.
8. No Verifund code, service, env var, model, payment workflow, transaction coordinator, or dependency exists. Nebius is the only external runtime dependency.
9. UI is responsive, keyboard-accessible, and meets WCAG AA contrast.

## 19. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A2A SDK 1.2.3 is new | Pin version; protocol tests cover card, tasks, streaming, cancellation; wrap in helper layer |
| LLM nondeterminism | Bounded action space, low temperature, structured output, validators, fallback |
| DeepSeek tool-calling inconsistency | Small tool set, repair attempt, scripted tests, configurable model |
| CopilotKit/AG-UI interrupt mismatch | Verify with an early vertical slice; keep the buyer interrupt payload small and documented |
| SQLite write contention | WAL, per-service DB, short transactions, no cross-process writes |
| State snapshot size | Keep summaries in AG-UI state; fetch full trace on demand |
| Approval trust gap | Document that receipt verification is buyer-side; no false claim of cross-org attestation |
| Registry SSRF | Local-origin restriction and explicit allowlist in production |
| Scope creep | Non-goals are explicit; no payments, fulfillment, or cloud infrastructure |

## 20. Implementation sequence

1. Foundation: contracts, schemas, config, logging, SQLite helpers, test harness.
2. Registry and A2A seller servers with Agent Cards, auth, task lifecycle, and protocol tests.
3. Seller LangGraph graphs, catalog, inventory, pricing policy, offers, orders, idempotency.
4. Buyer LangGraph graph, A2A client, scoring, negotiation subgraphs, approval interrupt, AG-UI endpoint, trace API.
5. CopilotKit console rewrite: chat, deal room, approval, A2A inspector, order view.
6. End-to-end wiring, seed/demo, Docker Compose, Playwright, docs, polish.

## 21. Definition of done

- All acceptance criteria pass.
- `README.md` explains architecture, setup, demo, protocol, adding a seller, and security limits.
- Extension schema docs and example frames are included.
- `.env.example` lists every required variable with safe defaults.
- No secrets are committed.
- The project runs from a clean checkout with `make setup && make dev`.
- No Verifund references exist outside the mandated directory name and the standalone constraint statement.
