# MarketMesh Commerce Extension for A2A

MarketMesh uses standard A2A 1.x tasks, messages, artifacts, and JSON-RPC transport. The
commerce semantics travel in a versioned A2A extension:

```
https://marketmesh.example/extensions/commerce/v1
```

The URI and its schema paths are identifiers only; they do not need to resolve for the
prototype. Schema files:

| Kind | Schema URL |
| --- | --- |
| RFQ | `.../schemas/rfq.json` |
| Offer | `.../schemas/offer.json` |
| Counteroffer | `.../schemas/counter-offer.json` |
| Accept offer | `.../schemas/accept-offer.json` |
| Purchase order | `.../schemas/purchase-order.json` |
| Order | `.../schemas/order.json` |
| Commerce error | `.../schemas/commerce-error.json` |

## Envelope

Every structured payload is an A2A `DataPart` with `media_type: application/json` and this
shape:

```json
{
  "schema": "https://marketmesh.example/extensions/commerce/v1/schemas/rfq.json",
  "schema_version": "1.0",
  "payload": {}
}
```

Messages also include a human-readable `TextPart`. Sellers read the first data part; text
is for observer readability and must not be used to carry prices or mandate terms.

## Agent Card

A commerce seller publishes:

- one JSON-RPC interface at `/a2a` with streaming enabled;
- the commerce extension as **required**;
- extension params `rating` and `sustainability_certified`;
- a bearer security scheme;
- skills for catalog search, quote, negotiation, and order.

The registry indexes cards by seller ID and category. The buyer independently fetches and
validates each card before opening a task, because registry discovery is not a trust
substitute.

## RFQ

Buyer to seller, creating a new task.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `request_id` | string | Stable ID for this RFQ |
| `run_id` | string | Buyer-side sourcing run |
| `category` | string | Such as `consumer-electronics` |
| `product_hint` | string | Product description |
| `quantity` | integer | Greater than zero |
| `required_by` | RFC 3339 timestamp | Delivery deadline |
| `constraints.min_warranty_months` | integer | Hard minimum |
| `constraints.min_returns_days` | integer | Hard minimum |
| `constraints.color` | string or null | Requested color |
| `preferences.sustainability` | boolean | Soft preference |
| `preferences.delivery_preference` | string or null | Optional description |
| `message` | string or null | Buyer note |

The buyer’s maximum budget is **not** part of the RFQ and is never sent to a seller.

## Offer

Seller to buyer, emitted as an artifact in the task stream.

| Field | Type | Notes |
| --- | --- | --- |
| `offer_id` | string | Stable within the seller |
| `request_id` | string | RFQ being answered |
| `seller_id` | string | Registry seller ID |
| `seller_name` | string | Display name |
| `seller_rating` | number | 0–5 |
| `task_id`, `context_id` | string or null | A2A correlation |
| `currency` | string | `USD` |
| `line_items[]` | array | SKU, name, quantity, base unit price, list price, warranty add-on, attributes |
| `subtotal_cents` | integer | Must equal line-item arithmetic |
| `shipping_cents` | integer | Zero in this demo |
| `total_cents` | integer | Must equal subtotal plus shipping |
| `delivery_days` | integer | Greater than zero |
| `delivery_date` | timestamp or null | Optional projected date |
| `warranty_months` | integer | Offered coverage |
| `returns_days` | integer | Offered return window |
| `valid_until` | RFC 3339 timestamp | Offer expiry |
| `terms.sustainability_certified` | boolean | Certification claim |
| `terms.stock_confidence` | number | 0–1 |
| `terms.split_shipment` | boolean | Incoming stock required |
| `terms.notes` | string or null | Optional note |
| `status` | enum | `proposed`, `final`, `accepted`, `rejected` |
| `round` | integer | Starts at 1 |
| `rationale` | string | Seller explanation |

The server rejects offers whose totals do not match their line items.

## Counteroffer

Buyer to seller, continuing an existing task.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `negotiation_round` | integer | At least 1 |
| `target_unit_price_cents` | integer or null | Buyer target |
| `requested_changes` | object | Strings, integers, or booleans |
| `rationale` | string | Human-readable reason |

Sellers may only choose a price from their policy ladder. A target below the seller floor
is rejected rather than forced into an invalid offer.

## Accept offer

Buyer to seller, binding the buyer to the final offer terms.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `offer_id` | string | Final offer being accepted |
| `round` | integer | Accepted round |
| `accepted_total_cents` | integer | Must match the offer |
| `accepted_by_buyer_task` | string or null | Buyer audit reference |

## Purchase order

Buyer to seller, sent only after the human approval interrupt resumes with an approved
decision.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `request_id` | string | Order request ID |
| `run_id` | string | Buyer run |
| `offer_id` | string | Accepted offer |
| `seller_id` | string | Winning seller |
| `quantity` | integer | Ordered quantity |
| `shipping_address` | object | Name, line 1, city, region, postal code, country |
| `approval.approval_id` | string | Receipt ID |
| `approval.approved_by` | string | Display identity |
| `approval.approved_at` | timestamp | Decision time |
| `approval.note` | string or null | Human note |
| `idempotency_key` | string | Repeat-safe request key |
| `expected_total_cents` | integer | Must match the accepted offer |

## Order

Seller to buyer, emitted as a terminal artifact.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `order_id` | string | Seller order ID |
| `offer_id` | string | Source offer |
| `seller_id` | string | Seller |
| `status` | enum | `confirmed`, `cancelled`, `failed` |
| `currency` | string | `USD` |
| `quantity` | integer | Ordered quantity |
| `total_cents` | integer | Must match expected total |
| `line_items[]` | array | Same shape as offer lines |
| `reserved_at` | timestamp | Stock reservation time |
| `eta` | timestamp | Simulated delivery estimate |
| `tracking_number` | string | Simulated tracking |
| `fulfillment.carrier` | string | Simulated carrier |
| `fulfillment.status` | string | Simulated status |

Repeating the same `idempotency_key` returns the existing order rather than reserving
stock twice.

## Commerce error

An artifact with this payload terminates a failed turn:

| Field | Type | Notes |
| --- | --- | --- |
| `code` | enum | `out_of_stock`, `offer_expired`, `below_floor`, `invalid_request`, `unsupported_constraint`, `conflict` |
| `message` | string | Diagnostic |
| `retryable` | boolean | Caller guidance |
| `details` | object | Structured context |

## Task lifecycle

1. Buyer fetches the seller card and opens an A2A session with `SendStreamingMessage`.
2. The RFQ creates a task. The seller emits an initial `Task` event, then a working status,
   an offer artifact, and an `input-required` status.
3. The buyer sends counteroffers against the same `task_id` and `context_id`. Task IDs stay
   stable across the negotiation.
4. The buyer sends `AcceptOffer`; the seller marks the task complete.
5. After human approval, the buyer sends a purchase order under the same context. The
   seller reserves stock transactionally and returns an order artifact.
6. Cancellation is available as standard A2A `CancelTask`; a rejected award never sends a
   purchase order at all.

Streaming responses are recorded in the buyer trace as inbound frames; buyer messages are
recorded as outbound frames before transmission. Authorization values are redacted before
persistence.

## Discovery

A2A defines Agent Cards but not a global registry. MarketMesh adds a small discovery
service that:

- accepts an authenticated card URL and category;
- fetches and validates the card;
- indexes a content hash, category, health, and last-seen timestamp;
- serves discovery by required extension and category.

The buyer still fetches the card directly and validates the extension URI, streaming
capability, transport binding, security scheme, and seller metadata.
