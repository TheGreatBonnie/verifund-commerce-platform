# Architecture

## Service boundaries

MarketMesh is a set of processes with explicit ownership:

| Service | Owns | Does not own |
| --- | --- | --- |
| Console | UI state, CopilotKit chat, approval presentation, trace/registry proxies | Prices, mandate validation, orders |
| Orchestrator agent | AG-UI entrypoint, mediated buyer/seller coordination, seller-call resumption | Mandate validation, ranking, stock, order IDs |
| Buyer agent | Mandate, discovery, negotiation orchestration, ranking, approval interrupt, purchase orders | Seller stock, seller cost floors |
| Registry | Agent Card index, categories, card hashes, health | Negotiation, trust decisions, orders |
| Seller agents | Catalog policy, quote generation, negotiation choices, stock, reservations, order IDs | Buyer budget, ranking, human approval |

Each seller has its own SQLite database and its own policy file. The buyer has its own
database and a separate LangGraph checkpoint database. The registry has only the card index.
No service shares an ORM session or database transaction with another.

## Protocol split

```text
Browser
  │  AG-UI (messages, shared state, interrupts; streaming)
  ▼
Next.js console ── proxy ──► Orchestrator FastAPI
                                │
                                │ mediates buyer and seller calls
                                ▼
                         Buyer FastAPI
                                │
                                │ A2A 1.x JSON-RPC over HTTP
                                │ SendStreamingMessage → SSE frames
                                ▼
                     Registry + three seller services
```

AG-UI is the human-facing agent protocol. A2A is the organization-to-organization commerce
protocol. Keeping them separate matters:

- The console never speaks A2A directly and never receives seller bearer tokens.
- Seller services expose only Agent Card, health, metrics, and authenticated A2A routes.
- The buyer is the only component that holds outbound seller credentials.
- Trace frames are persisted by the buyer and read through a console proxy.

## Buyer graph

The buyer LangGraph graph has these nodes:

```text
interpret_brief
  → discover_sellers
  → plan_sourcing
  → prepare_mediated
  → select_next_seller ↔ process_seller (mediated, one seller at a time)
  → rank_offers
  → await_approval (interrupt)
  → place_order ──┐
  └ reject → cancel_losers → finalize
```

Key properties:

- The brief is parsed by a planner but normalized against the `Mandate` schema.
- Discovery validates Agent Cards independently of the registry.
- Negotiation runs per seller through mediated seller calls, with stable seller task and context IDs.
- The RFQ never contains `max_total_cents`. A guardrail rejects any RFQ text that leaks the
  budget in dollars or cents.
- Offers are revalidated: seller ID, request ID, recomputed line-item arithmetic, and
  total arithmetic must match.
- Ranking and hard-constraint filtering are deterministic functions in `commerce_core`.
- The winning award is a `AwardPackage` containing the winner, alternatives, scores,
  savings, and mandate checks.

## Approval boundary

The approval is a LangGraph `interrupt` inside `await_approval`. It occurs **before** any
`AcceptOffer` or `PurchaseOrderRequest` is sent to the winner. The interrupt payload is
surfaced through AG-UI and rendered in both the chat rail and the Deal Room using the same
CopilotKit interrupt handler.

On resume:

- `approved: true` requires a non-empty `approved_by`; the buyer creates an approval receipt
  and proceeds to `place_order`.
- `approved: false`, or the AG-UI cancellation sentinel, proceeds to `cancel_losers`.
- The seller never sees an approval decision that did not come through this graph resume.

The seller treats the purchase order’s approval receipt as an assertion from the buyer. This
prototype does not provide cryptographic proof of human identity.

## Seller graph

Each seller turn uses a small LangGraph state machine:

```text
kind_from_envelope
  → RFQ: quote at policy price
  → counter: choose an allowed concession or accept/reject
  → accept: persist accepted offer
  → purchase order: validate, reserve stock, create order
```

The planner may propose an action and rationale, but seller policy constrains every price
and warranty option. Invalid planner output falls back to a deterministic decision.

Orders reserve stock inside a single SQLite transaction. An idempotency key maps to one
order ID; a duplicate purchase order returns the original order without a second
reservation.

## Data ownership

| Data | Store |
| --- | --- |
| Buyer run summary and A2A trace frames | `data/buyer.db` |
| LangGraph checkpoints and interrupt state | `data/buyer-checkpoints.db` |
| Orchestrator ADK session state | In memory (not persisted) |
| Agent Card index | `data/registry.db` |
| Northwind policy state, offers, stock, orders | `data/northwind.db` |
| CircuitForge policy state, offers, stock, orders | `data/circuitforge.db` |
| Aurora policy state, offers, stock, orders | `data/aurora.db` |

The A2A task store used by each seller is the same seller SQLite database, namespaced by
the A2A SDK’s tables.

## Failure handling

- **Unavailable seller** — discovery still returns others; the buyer fans out to validated
  sellers only. A failed seller produces an error negotiation record, not a failed run.
- **Invalid card** — registry registration returns an error; buyer discovery skips it and
  records the reason.
- **Protocol violation** — a seller error artifact or an offer that fails revalidation is
  recorded against that seller; other sellers continue.
- **No eligible offer** — the graph ends in `no_award` with structured failure details and
  never opens an approval.
- **Duplicate order** — idempotency returns the original order.
- **Expired offer** — the seller rejects the purchase order with `offer_expired`; the buyer
  reports `order_failed`.
- **Stock race** — reservation is transactional; a loser receives `out_of_stock` or an
  atomic SQLite conflict.
- **Approval rejected** — losers are cancelled through A2A `CancelTask`; no order exists.
- **Trace failure** — the UI shows a trace feed error; the commerce run itself continues.
