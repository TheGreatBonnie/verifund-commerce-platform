# Verifund PayPal Frontend Checkout Design

## 1. Context and problem

MarketMesh already installs two PayPal packages in the console:

- `@paypal/paypal-server-sdk@2.5.0` (Node/TypeScript server SDK)
- `@paypal/react-paypal-js@10.6.1` (React bindings for the PayPal JS SDK)

Neither is used anywhere in the console today. All PayPal REST traffic is performed by
the Python Verifund control plane (`apps/verifund_control_plane`) over `httpx`, and
the buyer completes funding through a redirect to PayPal's hosted page (or to the
local fake checkout in `VERIFUND_MODE=fake`).

The goal of this design is to use the installed SDKs to:

1. Replace the redirect-based PayPal checkout with an embedded PayPal checkout card
   rendered inside the CopilotKit chat (a new HITL card), so the buyer can approve
   funding without leaving the run.
2. Consolidate the PayPal *checkout* surface (order create + capture) into the Next.js
   server using `@paypal/paypal-server-sdk`, while keeping the Python control plane as
   the settlement authority for payouts, webhooks, reconciliation, and receipt signing.

Payouts and webhook verification have no support in the server SDK and remain in Python.

### 1.1 Locked decisions (2026-11-02)

These were settled during review and constrain everything below.

1. **Abandoned checkout does not kill the deal.** If the buyer opens the popup and walks
   away, the transaction stays `FUNDING_PENDING` until the funding deadline. A new order
   may be attached only once the previous order is dead (voided, expired, or past the
   funding deadline).
2. **The verifund agent owns `funding/prepare`.** It runs as a graph node between the
   funding approval and the checkout card. Transport is the existing buyer-agent internal
   settlement API, because the verifund agent holds no control-plane ops token and must
   not gain one.
3. **`prepare_funding` mirrors `fund()`'s binding checks exactly** — agreement
   version/hash binding, approval version/hash binding, and approval presence. The
   embedded path must not accept anything the redirect path would reject.
4. **Explicit cancel is terminal; `PENDING` pauses.** A buyer who explicitly cancels the
   popup ends the run (transaction canceled with `buyer_cancelled`). A capture that
   PayPal reports as `PENDING` (for example eCheck) pauses the run until `refresh` or the
   webhook settles it; the agent never proceeds to the purchase order while settlement is
   pending.
5. **The card falls back to hosted checkout on SDK failure.** If the PayPal SDK script
   or the popup cannot load, the card offers "Pay on PayPal's site", which returns
   `status: "fallback"` to the agent. The verifund graph then takes its existing redirect
   node, and the existing `CheckoutCard` renders the `checkout_url`. The link cannot be
   rendered from the card itself: the embedded path creates no PayPal order until the
   buyer clicks, so there is nothing to link to until the redirect node runs.

## 2. Non-goals

- No changes to `VERIFUND_MODE=fake`. Fake mode keeps `FakePaymentPort` and the
  redirect fake checkout.
- No live-money support. Sandbox only; the control plane still rejects the live host.
- No vault, subscriptions, or transaction-search UI in v1 (server SDK exposes them,
  but they are out of scope for this change).
- No removal of the Python PayPal port; it remains the authority for payouts and
  webhook verification and the fallback for fake mode.
- No new control-plane privileges for the verifund agent.

## 3. Current flow (baseline)

1. Buyer and seller accept the same agreement version/hash.
2. Human approves funding in chat (`request_verifund_funding_approval`).
3. The orchestrator calls `verifund_fund`, which resumes the verifund graph; the graph
   calls the buyer agent, which calls the control plane `POST /transactions/{id}/fund`.
4. `service.fund()` transitions `AGREED -> FUNDING_PENDING`, issues signed
   checkout/return/cancel links, and calls `payments.create_order()` (Python port).
5. The control plane returns `checkout_url` (payer action URL).
6. The console opens/redirects to that URL; the buyer pays on PayPal's hosted page.
7. On return, `GET /return/{token}` calls `refresh_funding()`, which captures the
   order and transitions to `FUNDED`, then the buyer agent places the purchase order.

## 4. Proposed architecture

### 4.1 Control plane (Python) changes

All new routes are ops-token protected. The start of funding in embedded mode is
`prepare` + `attach`, and settlement stays where it already is: `refresh` and the
webhook handler, both funneling into `apply_capture()`.

**A. `prepare_funding(transaction_id)`**

- `POST /transactions/{transaction_id}/funding/prepare`
- Validates the transaction and **pins the funding deadline** in `record.deadlines`
  (reusing it when already set). It does **not** change state, does **not** issue links,
  and does **not** call PayPal.
- Mirrors `fund()`'s binding checks exactly, in the same order:
  - state is `AGREED` or `FUNDING_PENDING` (anything else is `409`),
  - `record.approval` exists,
  - agreement exists (`agreement_service.get_by_transaction`) and
    `verify_funding_binding` passes for the record's agreement version/hash,
  - the approval's `agreement_version`/`agreement_hash` bind the same version.
- **Deliberately leaves the state at `AGREED`.** The fallback in §4.4 runs the existing
  `/fund` endpoint, which rejects a transaction that is already `FUNDING_PENDING` without
  a provider order. Prepare must not consume that state transition; `attach` performs it
  when the embedded order is created.
- Returns:
  ```json
  {
    "transaction_id": "vf_...",
    "amount_cents": 340000,
    "currency": "USD",
    "expires_at": "2026-11-02T18:00:00+00:00",
    "agreement_version": 3,
    "agreement_hash": "<64 hex>",
    "order_attempt": 0,
    "provider_order_id": null
  }
  ```
- Idempotent without an idempotency key: the deadline is written once and returned
  unchanged on every subsequent call. If the deadline write loses a version race
  (`VerifundError("conflict", ...)`), re-read the record and return its session — a
  concurrent prepare is indistinguishable from a retry.
- The returned `order_attempt` is `0` before the first attach and equals the attached
  order's attempt afterwards; callers use it to derive the create/capture keys (§4.1 E).

**B. `attach_funding_order(transaction_id, order_id)`**

- `POST /transactions/{transaction_id}/funding/attach-order`
- Called by the Next.js server **immediately after order creation**, before the buyer
  approves anything, so the control plane knows the order id even if the buyer abandons
  and even if the capture never reaches `refresh`.
- Accepts `AGREED` (and then performs the `AGREED -> FUNDING_PENDING` transition, sets
  the deadline if prepare had not) or `FUNDING_PENDING` (plain update). Sets
  `funding.status = "pending"`, `funding.provider_order_id`, and
  `funding.order_attempt` (1 on first attach).
- Idempotent on `order_id`.
- Replaces an existing order id only when the previous order is dead:
  - `payments.get_order(existing)` reports `VOIDED` or `EXPIRED`, **or**
  - the funding deadline has passed.
  Otherwise a different `order_id` is a `409 conflict`. This is what makes the locked
  "abandon, then retry" behavior possible without allowing an arbitrary swap.
- Amount/currency are **not** re-verified here. The control plane has already bound the
  amount in `prepare`, the Next.js server derives it server-side (§4.3), and the
  authoritative comparison happens in `apply_capture()` (`capture.amount_cents ==
  record.amount_cents and capture.currency == record.currency`), which routes a mismatch
  to `REVIEW_REQUIRED`. The real guarantee is "no mismatched capture can fund a deal",
  not "attach rejects a mismatched order"; this spec states it accurately rather than
  claiming an attach-time check the code does not perform.

**C. Reuse `POST /transactions/{transaction_id}/funding/refresh`**

- Already exists. It resolves `funding.provider_order_id`, calls `get_order()`, captures
  when the order is `APPROVED`, and calls `apply_capture()` for each capture.
- One change: the capture idempotency key becomes attempt-aware,
  `capture:{transaction_id}:v{order_attempt}` (default `1`), so a replacement order
  cannot replay a capture response from the dead one. The Next.js capture action uses the
  same key, which preserves PayPal's request-id dedupe between the two callers.
- `apply_capture()` already handles `COMPLETED` → `FUNDED`, mismatched funds →
  `REVIEW_REQUIRED`, `PENDING` → funding stays `pending`, reversed → `REVIEW_REQUIRED`,
  and other statuses → `FAILED`. No change.

**D. Explicit cancel reuses the existing endpoint**

- `POST /transactions/{transaction_id}/cancel` with `reason_code: "buyer_cancelled"`.
- `service.cancel()` already permits this from `FUNDING_PENDING` and revokes seller
  tokens. This is intentional now: an explicit buyer cancel *is* a terminal transaction
  outcome, unlike an abandoned popup.

**E. Idempotency keys**

| Operation | Key | Owner |
|---|---|---|
| Redirect order create (existing) | `fund:{txn}:v1` | Python `fund()` |
| Embedded order create | `fund:{txn}:embedded:v{n}` | Next.js, `n = order_attempt + 1` (so the first order is `v1`) |
| Capture | `capture:{txn}:v{n}` | Next.js and Python `refresh_funding`, `n = order_attempt` (default `1`) |

The `embedded` segment prevents a collision with the redirect flow's existing key; the
attempt number prevents replaying a dead order's response.

### 4.2 Checkout approval plumbing (contracts, graph, orchestrator)

The existing HITL cards are frontend tools that the orchestrator LLM calls after a
verifund task result reports `status == "approval_required"` with a matching
`approval_type`. A card rendered *after* funding approval therefore needs a new approval
type; the orchestrator cannot emit a HITL view on its own.

- **Contracts** (`packages/verifund_contracts/verifund_contracts/a2a.py`):
  - `VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED = "funding_checkout_required"`.
  - `approval_type: Literal["funding", "checkout", "release"]`.
  - The post-validator's checkpoint→approval map gains
    `FUNDING_CHECKOUT_REQUIRED: "checkout"`.
  - New `CheckoutDecision` model: `{status: "completed"|"canceled"|"fallback",
    transaction_id, order_id?, capture_id?, projection?, idempotency_key}`.
- **Verifund agent service** (`_checkpoint_result`, `CHECKPOINT_STATES`): map the new
  checkpoint to `approval_type="checkout"`, `next_action="complete_checkout"`, and
  `TransactionState.FUNDING_PENDING`.
- **Verifund agent graph**: after `await_funding_approval` approves, an embedded-mode
  branch runs `prepare_checkout` (calls the buyer-agent prepare endpoint), then
  `await_checkout` returns the approval checkpoint. Resume routing:
  - `completed` → `await_funding_settlement`
  - `canceled` → `cancel_transaction` (buyer client, `buyer_cancelled`) → `finalize`
  - `fallback` → `fund_transaction` (the existing redirect node) → `await_funding_settlement`.
    This path requires the transaction to still be `AGREED` (no attached order), which is
    the case whenever the SDK failed before `createOrder`. If an order is already
    attached, the node returns to `await_checkout` instead so the buyer can retry the popup.
- **Orchestrator**: `_view()` gains a `checkout` branch emitting
  `hitl.tool = "request_verifund_paypal_checkout"` with `_checkout_args()`; a new
  `resume_checkout()` mirrors `resume_funding()`; a new `verifund_checkout` backend tool
  accepts the `CheckoutDecision`; the system prompt gains the checkout rules (call the
  frontend tool with `hitl.args` unchanged, then `verifund_checkout`; never call
  `verifund_evidence_review` directly after checkout).

### 4.3 Next.js server changes

**Environment variables**

- Public (browser-safe): `NEXT_PUBLIC_PAYPAL_CLIENT_ID`,
  `NEXT_PUBLIC_PAYPAL_ENVIRONMENT` (`sandbox` | `production`).
- Server-only: `PAYPAL_CLIENT_SECRET`.
- `NEXT_PUBLIC_PAYPAL_CLIENT_ID` must equal the control plane's `PAYPAL_CLIENT_ID`.
  Add a preflight assertion for this; a mismatch otherwise surfaces only when the popup
  fails.

**Singleton client (`apps/console/lib/paypal.ts`)**

One `Client` + `OrdersController` per serverless warm start, reading
`NEXT_PUBLIC_PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` /
`NEXT_PUBLIC_PAYPAL_ENVIRONMENT`. Exports:

- `createPayPalOrder(amount: string, currency: string, idempotencyKey: string)` using
  `OrdersController.createOrder({ body: { intent: CheckoutPaymentIntent.Capture,
  purchaseUnits: [{ amount: { currencyCode, value: amount } }] }, paypalRequestId })`.
- `capturePayPalOrder(orderId, idempotencyKey)` returning
  `{ captureId, status, amountCents, currency }` from
  `purchaseUnits[0].payments.captures[0]`.

**Server actions (`apps/console/app/actions.ts`, `"use server"`)**

Server actions are the chosen boundary (matches the sample, type-safe, and they already
exist in this app for agreements).

- `createOrderAction({ transactionId })`
  - Reads amount/currency from the control plane `funding/prepare` **server-side**. The
    browser never supplies an amount.
  - Asserts the caller may act on the transaction (see §6).
  - Creates the order, then calls `funding/attach-order` before returning `{ id }`.
  - Reuses an existing `provider_order_id` only while `expires_at` is still in the
    future, so a retry after an abandoned popup resumes the same order. Past the deadline
    it creates a new order at `v{order_attempt + 1}` and attaches it, which `attach`
    permits because the deadline has passed.
- `captureOrderAction({ transactionId, orderId })`
  - Captures with `capture:{transactionId}:v{n}`, calls `funding/refresh`, and returns
    `{ orderId, captureId, status, amountCents, currency, settlementState }`.
  - `settlementState` comes from the refresh projection, so the card can distinguish
    `FUNDED` from captured-but-pending.
- `pollFundingAction({ transactionId })` → `funding/refresh`, used by the card while a
  capture is pending.
- `controlPlaneJson` returns a `Response`; every action must `await res.json()` and throw
  on `!res.ok` rather than returning the `Response` (a `Response` is not serializable
  across the server-action boundary).

### 4.4 Chat UI changes

Register a new CopilotKit HITL tool in `apps/console/features/chat/chat.tsx`:

- Name: `request_verifund_paypal_checkout`
- Available when `verifundToolsEnabled(mode)` is true AND `mode === "sandbox"`.
- Parameters: `{ transaction_id, amount_cents, currency, expires_at, message }`.
- Render component: `PayPalCheckoutCard` (new, in `verifund-tools.tsx`).
- Render result state: a completed checkout renders the settlement status; a canceled
  checkout renders a terminal "funding canceled" note.

`PayPalCheckoutCard`:

- Wraps children in `PayPalProvider` from `@paypal/react-paypal-js/sdk-v6` with
  `clientId={process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID!}` and
  `environment={process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT}`,
  `components={["paypal-payments"]}`, `pageType="checkout"`.
- Renders `PayPalOneTimePaymentButton` with `presentationMode="auto"`:
  - `createOrder`: calls `createOrderAction({ transactionId })` and returns
    `{ orderId: id }`.
  - `onApprove`: `captureOrderAction({ transactionId, orderId })`, then
    `respond({ status, order_id, capture_id, projection })`. If the result is
    `PENDING`, keep the card in a "confirming payment" state and poll
    `pollFundingAction` until `FUNDED` or the funding deadline, then respond.
  - `onCancel`: `respond({ status: "canceled", canceled: true })`.
  - `onError` / SDK load timeout: switch to the fallback view.
- Fallback view: a "Pay on PayPal's site" button that responds
  `{ status: "fallback" }`. The verifund graph routes to its existing redirect node, and
  the existing `CheckoutCard` renders the `checkout_url` in the chat. This keeps the
  redirect flow, its binding checks, and its return handling unchanged.
- Shows amount, currency, transaction id, expiry, and an `aria-live` status line.
- Disables the button while a request is in flight (double-click safety).

The orchestrator calls `request_verifund_paypal_checkout` with the `hitl.args` from the
checkout approval result; the verifund agent already ran `prepare`, so the card never
prepares anything.

### 4.5 Sequence

1. Agreement approved by both parties.
2. Chat shows `FundingApprovalCard` (existing).
3. On approve, the verifund graph calls the buyer-agent prepare endpoint → control plane
   `funding/prepare`, which validates and pins the deadline (state stays `AGREED`).
4. Verifund task returns `approval_required` with `approval_type="checkout"`; the
   orchestrator renders `request_verifund_paypal_checkout`.
5. Buyer clicks the PayPal button; Next.js creates the order (server-derived amount) and
   attaches it, which transitions the transaction to `FUNDING_PENDING`.
6. Buyer approves in the PayPal popup.
7. Next.js captures the order.
8. Next.js calls `funding/refresh`; the control plane verifies the capture against
   PayPal and transitions to `FUNDED`.
9. Card responds; the orchestrator resumes the verifund task with a `CheckoutDecision`.
10. Agent continues: purchase order, evidence, verification, release HITL, payout.

## 5. Error handling

- **Prepare failure**: the funding approval has already been given; surface the error in
  chat. The transaction is still `AGREED`, so the redirect fallback and a retried prepare
  are both safe.
- **Create failure**: surface the error in the card; retry reuses the same attempt key.
- **Attach failure after a successful create**: retry with backoff before returning the
  order id to PayPal. If it never succeeds, the order exists at PayPal but the control
  plane will not see it; the card reports the order id so the operator can reconcile, and
  the redirect fallback remains available.
- **Capture failure**: show the error; refresh will reconcile if a capture actually
  succeeded.
- **Capture `PENDING`**: card enters "confirming payment", polls `refresh` (2s, backing
  off, bounded by the funding deadline). The agent is not resumed until `FUNDED`; a
  deadline expiry responds as a failure, not a success.
- **Attach/refresh failure after a successful capture**: retry with backoff; on permanent
  failure the card shows "payment captured; settlement sync pending" and the reconciler
  or webhook recovers. This only works because attach happened at create time.
- **Buyer cancels**: card responds `canceled`; the verifund graph cancels the transaction
  with `buyer_cancelled`. Terminal.
- **Buyer abandons** (closes popup without choosing cancel): nothing is canceled. The
  transaction stays `FUNDING_PENDING` to the funding deadline; the card can be re-opened
  and the same order retried, and only a dead order allows attaching a new one.
- **PayPal voids the order before the deadline**: limited by design. `prepare` performs
  no PayPal read, so it cannot tell a live order from a voided one; the card surfaces the
  failure and the transaction must be canceled (or the deadline extended) before a new
  order can be attached. This is the accepted cost of keeping prepare PayPal-free.
- **SDK/popup unavailable**: automatic hosted-checkout fallback (§4.4) — the card
  responds `fallback`, the graph runs the redirect node, and the buyer finishes on
  PayPal's hosted page.
- **Webhook fallback**: unchanged. `PAYMENT.CAPTURE.COMPLETED` etc. still drive
  `apply_capture` via the existing handler.

## 6. Security

- PayPal client secret never leaves the Next.js server.
- Control plane ops token is server-side only (existing pattern). The verifund agent does
  **not** gain an ops token; prepare is proxied through the buyer agent.
- Amount authority is server-side: the create action reads the amount from `prepare`,
  never from browser input.
- Every server action validates that the `transactionId` belongs to the caller's run
  before touching PayPal or the control plane. The ops token otherwise makes these
  actions an unauthenticated privileged proxy for any known transaction id.
- `prepare` enforces the same agreement/approval binding as `fund`; a captured amount or
  currency that does not match the transaction cannot fund it (`apply_capture` routes the
  mismatch to `REVIEW_REQUIRED`).
- `attach` replaces an order id only when the previous order is provably dead.
- Capture keys are attempt-aware so a dead order's capture response cannot be replayed.
- The redirect fallback reuses `/fund`, so it inherits the same validations.
- No new public surface beyond the existing console origin.

## 7. Testing strategy

- **Python**: unit tests for `prepare_funding` (state stays `AGREED`, deadline pinned
  once, mirrored binding rejections, race retry), `attach_funding_order` (state
  transition, idempotent, conflict, replacement after deadline/void), the new routes via
  `TestClient` with the ops token, and the attempt-aware capture key in
  `refresh_funding`.
- **Contracts**: a test that `approval_required` with
  `FUNDING_CHECKOUT_REQUIRED` requires `approval_type="checkout"`, and that other
  checkpoints still reject it.
- **Verifund agent**: graph test for the embedded branch (prepare → checkout approval →
  completed/canceled/fallback routing) mirroring `test_verifund_agent_graph.py`.
- **Orchestrator**: `_view()` emits the checkout HITL tool with the expected args;
  `resume_checkout` passes the decision through; the prompt mentions the tool.
- **Next.js actions**: Vitest with mocked `@paypal/paypal-server-sdk` and
  `control-plane-proxy` — create (amount from prepare, attach ordering), capture,
  pending, redirect fallback, error, and non-OK control-plane responses.
- **Chat component**: Vitest/RTL for `PayPalCheckoutCard` with mocked action modules —
  button render, success, pending polling, cancel, error, fallback, and double-click.
- **Fake mode**: unchanged; existing `verifund-e2e` must still pass.
- **Sandbox smoke**: update `verifund-sandbox-smoke.py` to drive the embedded button (or
  document manual steps) and record order/capture ids.

## 8. Rollout

1. Land the contract/checkpoint/approval-type change with tests (nothing changes behavior
   until the graph emits it).
2. Land control plane `prepare`/`attach` and the attempt-aware capture key behind the
   existing ops token.
3. Land Next.js `lib/paypal.ts`, server actions, and `PayPalCheckoutCard`.
4. Land the verifund agent `prepare_checkout`/`await_checkout` nodes and the orchestrator
   tool + prompt.
5. Feature flag `VERIFUND_CHECKOUT_MODE=embedded|redirect`, default `redirect`, checked by
   the verifund graph **and** by the server actions (an old tab must not create orders
   while the deployment is in redirect mode). Keep the redirect flow as the fallback path
   for one release cycle.
6. Update `docs/verifund-paypal-sandbox.md` and `.env.example` with the console env vars
   and the embedded checkout steps.

## 9. Open questions

- Should the funding deadline be shortened in embedded mode? The coupon-style PayPal
  order lifetime is roughly three hours, shorter than a long `funding_timeout_hours`;
  the attach rule tolerates that, but the card's expiry copy should match reality.
- Do we want to surface `order_attempt` in the run timeline, or only in logs?
- Should a `REVIEW_REQUIRED` outcome from a funding mismatch be actionable from the same
  card, or left to the existing review UI?

## 10. Implementation notes from the PayPal getting-started sample

The local buy-button sample (outside this repo) shows the canonical minimal integration
and confirms several decisions above:

- Singleton `Client`/`OrdersController` per serverless warm start (`lib/paypal.ts`).
- Create orders with `intent: CheckoutPaymentIntent.Capture` and a single purchase unit
  `{ amount: { currencyCode, value } }`; no redirect URLs are needed for the popup flow.
- Capture with `OrdersController.captureOrder({ id: orderId })` and read the capture from
  `purchaseUnits[0].payments.captures[0]`.
- Expose create/capture as Next.js Server Actions (`"use server"`).
- Render `PayPalProvider` with `clientId` from `NEXT_PUBLIC_PAYPAL_CLIENT_ID` and
  `environment` from `NEXT_PUBLIC_PAYPAL_ENVIRONMENT`, `components={["paypal-payments"]}`,
  `pageType="checkout"`.
- Use `PayPalOneTimePaymentButton` with `presentationMode="auto"`; its `createOrder`
  callback returns `{ orderId }` (no arguments).
- Keep `PAYPAL_CLIENT_SECRET` server-only; `NEXT_PUBLIC_PAYPAL_CLIENT_ID` is public.

The installed `@paypal/react-paypal-js@10.6.1` does expose the `./sdk-v6` subpath and all
of these exports, so the sample's structure maps directly onto the console.
