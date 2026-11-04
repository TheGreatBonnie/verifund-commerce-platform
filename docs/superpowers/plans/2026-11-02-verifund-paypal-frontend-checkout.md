# Verifund PayPal Frontend Checkout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the already-installed `@paypal/paypal-server-sdk` and `@paypal/react-paypal-js` to add an embedded PayPal checkout card in the CopilotKit chat, while keeping the Python control plane as the settlement authority.

**Architecture:** The verifund agent owns `funding/prepare` (transported through the buyer agent's internal settlement API). Next.js owns PayPal order create/capture and attaches the order id to the control plane at creation time. A new `checkout` approval type carries the card to the orchestrator. The control plane's existing `funding/refresh` verifies the capture and transitions to `FUNDED`. Fake mode is unchanged; redirect checkout remains the fallback.

**Tech Stack:** Python 3.12 / FastAPI control plane, LangGraph verifund agent, Google ADK orchestrator, Next.js 15 App Router, CopilotKit 1.79, `@paypal/paypal-server-sdk@2.5.0`, `@paypal/react-paypal-js@10.6.1`.

**Spec:** `docs/superpowers/specs/2026-11-02-verifund-paypal-frontend-checkout-design.md`

## Global Constraints

- Sandbox only; the control plane still rejects `https://api-m.paypal.com`.
- `PAYPAL_CLIENT_SECRET` and the ops token are server-side only. The verifund agent does not gain an ops token.
- Fake mode (`VERIFUND_MODE=fake`) is untouched; `make verifund-e2e` must still pass.
- Amounts cross boundaries as integer cents; convert to a 2-decimal string only at PayPal.
- Amount authority is server-side: never accept an amount from the browser.
- Idempotency keys: embedded create `fund:{txn}:embedded:v{n}` with `n = order_attempt + 1`; capture `capture:{txn}:v{n}` with `n = order_attempt` (default 1).
- An explicit cancel is terminal; an abandoned popup leaves the transaction `FUNDING_PENDING` until the funding deadline.
- Attach happens at order creation, not after capture.
- `controlPlaneJson` returns a `Response`: parse it and check `ok` in every server action.

---

### Task 1: Contract — checkout checkpoint and approval type

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/a2a.py`
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Test: `tests/unit/test_verifund_contracts.py`

**Interfaces:**
- Produces: `VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED`,
  `VerifundTaskResult.approval_type` including `"checkout"`, and
  `CheckoutDecision(status, transaction_id, order_id?, capture_id?, projection, idempotency_key)`.

- [ ] **Step 1: Write a failing contract test** asserting (a) `approval_required` with
  `checkpoint=FUNDING_CHECKOUT_REQUIRED` and `approval_type="checkout"` validates,
  (b) the same checkpoint with `approval_type="funding"` raises, and (c)
  `CheckoutDecision(status="completed", ...)` without a projection raises.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_verifund_contracts.py -q` → FAIL.
- [ ] **Step 3: Implement**

```python
# a2a.py
class VerifundCheckpoint(StrEnum):
    ...
    FUNDING_CHECKOUT_REQUIRED = "funding_checkout_required"

class VerifundTaskResult(VerifundModel):
    ...
    approval_type: Literal["funding", "checkout", "release"] | None = None

# _checkpoint_contract
        if self.status == "approval_required":
            expected = {
                VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: "funding",
                VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED: "checkout",
                VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: "release",
            }.get(self.checkpoint)
```

```python
# models.py
class CheckoutDecision(VerifundModel):
    status: Literal["completed", "canceled", "fallback"]
    transaction_id: str = Field(min_length=1)
    order_id: str | None = None
    capture_id: str | None = None
    projection: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _completed_requires_projection(self) -> CheckoutDecision:
        if self.status == "completed" and not self.projection:
            raise ValueError("completed checkout requires a settlement projection")
        return self
```

- [ ] **Step 4: Run** the test → PASS.
- [ ] **Step 5: Commit** `feat(verifund): add checkout approval contract`.

---

### Task 2: Control plane `prepare_funding`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_prepare_funding.py`

**Interfaces:**
- Produces: `VerifundService.prepare_funding(transaction_id, *, actor) -> dict` returning
  `{transaction_id, amount_cents, currency, expires_at, agreement_version, agreement_hash,
  order_attempt, provider_order_id}`. **Does not change state and issues no links.**
- Consumes: `_funding_deadline`, `_iso`, `_projection`, `repo.update_transaction` (all
  existing).

- [ ] **Step 1: Failing tests** in a fake-mode fixture (reuse
  `tests/unit/test_verifund_fake_payments.py` helpers) for:
  - the state stays `AGREED` and `deadlines.funding` is persisted, with `expires_at`,
    `amount_cents`, `currency`, and `order_attempt == 0` in the result;
  - replay returns the same `expires_at` and bumps the record version at most once;
  - a `FUNDING_PENDING` record with an attached order returns its `provider_order_id`;
  - a transaction without approval raises `invalid_state`;
  - a transaction whose approval binds a different version raises `hash_mismatch`;
  - a transaction in any other state raises `invalid_state`.
- [ ] **Note:** prepare must not transition to `FUNDING_PENDING`; `/fund` (the fallback)
  rejects that state, and `attach` owns the transition.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_verifund_prepare_funding.py -q` → FAIL.
- [ ] **Step 3: Implement** (after `fund`):

```python
    def _funding_session(self, record: TransactionRecord) -> dict[str, Any]:
        funding = record.funding or {}
        return {
            "transaction_id": record.transaction_id,
            "amount_cents": record.amount_cents,
            "currency": record.currency,
            "expires_at": self._iso(self._funding_deadline(record)),
            "agreement_version": record.agreement_version,
            "agreement_hash": record.agreement_hash,
            "order_attempt": int(funding.get("order_attempt") or 0),
            "provider_order_id": funding.get("provider_order_id"),
        }

    async def prepare_funding(self, transaction_id: str, *, actor: str) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state == TransactionState.FUNDING_PENDING:
            return self._funding_session(record)
        if record.state != TransactionState.AGREED:
            raise VerifundError(
                "invalid_state", "transaction is not ready for funding", status_code=409
            )
        if not record.approval:
            raise VerifundError("invalid_state", "buyer approval is required", status_code=409)

        agreement = await self.agreement_service.get_by_transaction(transaction_id)
        if agreement is None:
            raise VerifundError("not_found", "agreement not found", status_code=404)
        txn_proj = await self._projection(record, "buyer")
        from verifund_control_plane.agreements.models import AgreementError
        try:
            await self.agreement_service.verify_funding_binding(
                agreement, txn_proj, record.agreement_version, record.agreement_hash
            )
        except AgreementError as exc:
            raise VerifundError(exc.code, exc.message, status_code=409)
        approval = record.approval or {}
        if approval.get("agreement_version") not in (None, record.agreement_version) or (
            approval.get("agreement_hash") is not None
            and approval.get("agreement_hash") != record.agreement_hash
        ):
            raise VerifundError(
                "hash_mismatch", "funding approval binds a different version", status_code=409
            )

        if (record.deadlines or {}).get("funding"):
            return self._funding_session(record)
        deadline = self._funding_deadline(record)
        try:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "deadlines": {
                            **(current.deadlines or {}),
                            "funding": self._iso(deadline),
                        }
                    },
                    audit=AuditInput(actor, "funding_prepared"),
                )
        except VerifundError as exc:
            # A concurrent prepare already stored the deadline; the read below is the retry.
            if exc.code != "conflict":
                raise
        return self._funding_session(await self.repo.get_transaction(transaction_id))
```

- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit** `feat(verifund): add prepare_funding without a PayPal call`.

---

### Task 3: Control plane `attach_funding_order`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_attach_funding_order.py`

**Interfaces:**
- Consumes: transaction in `AGREED` or `FUNDING_PENDING`; `payments.get_order`.
- Produces: `attach_funding_order(transaction_id, order_id, *, actor) -> dict` (buyer
  projection) with `funding.provider_order_id` and `funding.order_attempt` set, and the
  transaction transitioned to `FUNDING_PENDING` when it was still `AGREED`.

- [ ] **Step 1: Failing tests** for: first attach moves `AGREED -> FUNDING_PENDING`,
  sets `funding.status == "pending"`, `order_attempt == 1`, and keeps the deadline
  prepare pinned; the same order id is idempotent; a different order id while the first
  is live raises `conflict`; a different order id after the funding deadline (or after
  `get_order` reports `EXPIRED`) is accepted with `order_attempt == 2`; attach on any
  other state (e.g. `FUNDED`) raises `invalid_state`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

```python
    async def _funding_order_is_dead(self, order_id: str) -> bool:
        try:
            order = await self.payments.get_order(order_id)
        except VerifundError:
            return True
        return order.status in {"VOIDED", "EXPIRED"} or bool(order.captures)

    async def attach_funding_order(
        self, transaction_id: str, order_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state not in {
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
        }:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting funding", status_code=409
            )
        funding = dict(record.funding or {})
        existing = funding.get("provider_order_id")
        attempt = int(funding.get("order_attempt") or 0)
        if existing and existing != order_id:
            past_deadline = self._now() >= self._funding_deadline(record)
            if not past_deadline and not await self._funding_order_is_dead(existing):
                raise VerifundError(
                    "conflict", "funding order already attached", status_code=409
                )
            attempt += 1
        elif not existing:
            attempt = max(attempt, 1)
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            current_funding = dict(current.funding or {})
            current_order = current_funding.get("provider_order_id")
            if current_order and current_order != order_id:
                raise VerifundError(
                    "conflict", "funding order changed; reload and retry", status_code=409
                )
            changes = {
                "funding": {
                    **current_funding,
                    "status": "pending",
                    "provider_order_id": order_id,
                    "order_attempt": attempt,
                }
            }
            if current.state == TransactionState.AGREED:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=TransactionState.AGREED,
                    new_state=TransactionState.FUNDING_PENDING,
                    changes={
                        **changes,
                        "deadlines": {
                            **(current.deadlines or {}),
                            "funding": self._iso(self._funding_deadline(current)),
                        },
                    },
                    events=[EventInput("funding_required", {}, actor)],
                    audit=AuditInput(actor, "funding_order_attached"),
                )
            elif current.state == TransactionState.FUNDING_PENDING:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes=changes,
                    audit=AuditInput(actor, "funding_order_attached"),
                )
            else:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting funding", status_code=409
                )
        return (await self._projection_for(transaction_id, "buyer")).model_dump(mode="json")
```

- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(verifund): attach embedded funding orders`.

---

### Task 4: Control plane routes

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Test: `tests/unit/test_verifund_prepare_attach_routes.py`

- [ ] **Step 1: Add pydantic request models** (do not read `request.json()` inline):

```python
class AttachFundingOrderRequest(BaseModel):
    order_id: str = Field(min_length=1)


@router.post(
    "/transactions/{transaction_id}/funding/prepare",
    dependencies=[Depends(require_ops)],
)
async def prepare_funding(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).prepare_funding(transaction_id, actor=actor(request))


@router.post(
    "/transactions/{transaction_id}/funding/attach-order",
    dependencies=[Depends(require_ops)],
)
async def attach_funding_order(
    transaction_id: str, body: AttachFundingOrderRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).attach_funding_order(
        transaction_id, body.order_id, actor=actor(request)
    )
```

- [ ] **Step 2: Write route tests** via `TestClient`: 200 with the ops token, 401/403
  without it, and a 409 surfaced from an attach conflict.
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_verifund_prepare_attach_routes.py -q`.
- [ ] **Step 4: Commit** `feat(verifund): expose prepare and attach-order routes`.

---

### Task 5: Attempt-aware capture key in `refresh_funding`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_capture_attempt_key.py`

- [ ] **Step 1: Failing test** asserting `refresh_funding` passes
  `capture:{txn}:v2` to `capture_order` when `funding.order_attempt == 2`, and
  `capture:{txn}:v1` when the field is absent (backward compatibility with the redirect
  flow).
- [ ] **Step 2: Implement** in `refresh_funding`:

```python
        attempt = int((record.funding or {}).get("order_attempt") or 1)
        ...
            captures = (
                await self.payments.capture_order(
                    str(order_id),
                    idempotency_key=f"capture:{transaction_id}:v{attempt}",
                ),
            )
```

- [ ] **Step 3: Run** the test, then `uv run pytest tests/unit/test_verifund_fake_payments.py tests/unit/test_verifund_sandbox_paypal.py -q` → all PASS.
- [ ] **Step 4: Commit** `fix(verifund): scope capture idempotency to the funding attempt`.

---

### Task 6: Buyer agent prepare proxy

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_client.py`
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement_api.py`
- Test: `tests/unit/test_verifund_agent_settlement.py` or a new
  `tests/unit/test_buyer_prepare_funding.py`

**Interfaces:**
- Produces: `SettlementClient.prepare_funding(transaction_id) -> dict`.
- Produces: `POST /internal/runs/{run_id}/settlement/prepare-funding` guarded by
  `_require_verifund_agent`, returning `{"checkout_session": {...}}`.
- Produces: `POST /internal/runs/{run_id}/settlement/cancel` guarded by
  `_require_verifund_agent`, accepting `{reason_code, note}` and delegating to
  `SettlementClient.cancel(transaction_id, CancelRequest(...))` (already exists at
  `settlement_client.py:343`). Needed by the checkout-cancel path.
- Produces: `BuyerInternalClient.prepare_funding(run_id)` and
  `BuyerInternalClient.cancel(run_id, *, reason_code, note)` in
  `apps/verifund_agent/verifund_agent/client.py` for Task 7.

- [ ] **Step 1: Failing test** for both routes: each resolves the transaction id for the
  run, calls the client, and rejects a caller without the verifund-agent token. For
  prepare, assert the session shape; for cancel, assert the `CancelRequest` passed
  through.
- [ ] **Step 2: Implement** mirroring the existing `fund()` client method and
  `internal_approve_funding` route; the service method calls
  `POST /transactions/{id}/funding/prepare` on the control plane with the ops headers.
- [ ] **Step 3: Run** the test → PASS.
- [ ] **Step 4: Commit** `feat(buyer): expose funding prepare for the verifund agent`.

---

### Task 7: Verifund agent graph — prepare and checkout approval

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/graph.py`
- Modify: `apps/verifund_agent/verifund_agent/service.py`
- Test: `tests/unit/test_verifund_agent_graph.py`

**Interfaces:**
- Produces: nodes `prepare_checkout`, `await_checkout`; state keys
  `checkout_session`, `checkout_decision`, `checkout_mode`.
- Produces: a `VerifundTaskResult` with `checkpoint=FUNDING_CHECKOUT_REQUIRED`,
  `approval_type="checkout"`, `next_action="complete_checkout"`.

- [ ] **Step 1: Failing graph tests** for the embedded branch: after an approved funding
  decision the graph calls `prepare_checkout` and stops at the checkout checkpoint with
  `approval_required`/`checkout`; resuming with `status="canceled"` routes to
  cancellation and completes without a purchase order; resuming with `status="fallback"`
  routes through `fund_transaction` to the funding-pending checkpoint; resuming with
  `completed` and a `FUNDED` projection reaches `stage == "funded"`; a projection for a
  different transaction raises `VerifundProtocolError`. Also assert redirect mode
  (`checkout_mode != "embedded"`) still goes approval → `fund_transaction`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_verifund_agent_graph.py -q` → FAIL.
- [ ] **Step 3: Implement**

```python
PENDING_CHECKPOINTS = {
    ...
    "await_checkout": VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED,
}

async def prepare_checkout(state: VerifundState, config: RunnableConfig) -> dict[str, Any]:
    run_id = state.get("run_id") or ""
    response = await _buyer(config).prepare_funding(run_id)
    session = response.get("checkout_session") or {}
    agreement = _agreement(state)
    if session.get("transaction_id") != agreement.transaction_id:
        raise VerifundProtocolError("prepare returned a mismatched transaction")
    return {"checkout_session": session, "stage": "checkout_required"}


def checkout_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    session = state.get("checkout_session") or {}
    return {
        "reason": "funding_checkout_required",
        "message": "Complete the PayPal checkout to fund this transaction.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "amount_cents": session.get("amount_cents"),
        "currency": session.get("currency"),
        "expires_at": session.get("expires_at"),
        **_binding(agreement),
        "responseSchema": CheckoutDecision.model_json_schema(),
    }


async def await_checkout(state: VerifundState, config: RunnableConfig) -> dict[str, Any]:
    value = interrupt(checkout_payload(state))
    decision = CheckoutDecision.model_validate(value)
    agreement = _agreement(state)
    if decision.transaction_id != agreement.transaction_id:
        raise VerifundProtocolError("checkout decision does not match the agreement")
    if decision.status == "canceled":
        return {"checkout_decision": decision.model_dump(mode="json"), "stage": "funding_canceled"}
    if decision.status == "fallback":
        return {"checkout_decision": decision.model_dump(mode="json"), "stage": "checkout_fallback"}
    projection = decision.projection or {}
    if projection.get("state") != TransactionState.FUNDED.value:
        raise VerifundProtocolError("checkout is not settled")
    return {"projection": projection, "funding_projection": projection, "stage": "funded"}


def approved_route(state: VerifundState) -> Literal["prepare_checkout", "fund_transaction"]:
    return "prepare_checkout" if state.get("checkout_mode") == "embedded" else "fund_transaction"


def checkout_route(state) -> Literal["await_funding_settlement", "fund_transaction", "cancel_transaction"]:
    stage = state.get("stage")
    if stage == "funding_canceled":
        return "cancel_transaction"
    if stage == "checkout_fallback":
        return "fund_transaction"
    return "await_funding_settlement"
```

Wire it in `build_graph`: add both nodes; replace the funding-decision conditional-edge
map so `approved` points at `approved_route` (mirroring how `funding_decision_route` is
wired today); add `prepare_checkout -> await_checkout`, a conditional edge on
`await_checkout` using `checkout_route`, and:

```python
async def cancel_checkout_transaction(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    agreement = _agreement(state)
    await _buyer(config).cancel(
        state.get("run_id") or agreement.run_id,
        reason_code=CancelReason.BUYER_CANCELLED.value,
        note="Buyer canceled the PayPal checkout",
    )
    return {"stage": "funding_rejected"}
```

`cancel_transaction` routes to `finalize_rejected`, which already maps
`stage == "funding_rejected"` to a canceled result. In `fund_transaction`, return the
fallback guard: if the control-plane session reports a `provider_order_id`, do not call
`/fund` (it rejects an already-funded-pending transaction) — return a
`checkout_fallback_unavailable` stage instead so the graph re-enters `await_checkout`.
Set `checkout_mode` from settings in the initial state, and map
`FUNDING_CHECKOUT_REQUIRED` to `approval_type="checkout"`/`next_action="complete_checkout"`
in `_checkpoint_result` plus
`CHECKPOINT_STATES[FUNDING_CHECKOUT_REQUIRED] = TransactionState.FUNDING_PENDING`.

- [ ] **Step 4: Run** the graph tests → PASS.
- [ ] **Step 5: Commit** `feat(verifund-agent): add embedded checkout checkpoint`.

---

### Task 8: Orchestrator view, tool, and prompt

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Test: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Consumes: `VerifundTaskResult` with `approval_type == "checkout"`.
- Produces: `view["hitl"] = {"tool": "request_verifund_paypal_checkout", "args": {...}}`,
  `VerifundLifecycle.resume_checkout(handle, decision)`, and the ADK tool
  `verifund_checkout(task_id, context_id, run_id, decision: dict)`.

- [ ] **Step 1: Failing tests** for `_view` (checkout tool name, and args containing
  exactly `transaction_id`, `amount_cents`, `currency`, `expires_at`, `message` from
  `result.data`), `resume_checkout` (uses `FUNDING_CHECKOUT_REQUIRED` and passes the
  decision through), and the tool's presence in the tool list.
- [ ] **Step 2: Implement**

```python
        if result.status == "approval_required":
            if result.approval_type == "funding":
                view["hitl"] = {"tool": "request_verifund_funding_approval", "args": self._funding_args(handle, result)}
            elif result.approval_type == "checkout":
                view["hitl"] = {"tool": "request_verifund_paypal_checkout", "args": self._checkout_args(handle, result)}
            elif result.approval_type == "release":
                view["hitl"] = {"tool": "request_verifund_release_approval", "args": self._release_args(handle, result)}
```

`_checkout_args` returns `{transaction_id, amount_cents, currency, expires_at, message}`
from `result.data`. `resume_checkout` mirrors `resume_funding`, using
`VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED` and
`CheckoutDecision.model_validate(decision)`.

```python
    async def verifund_checkout(
        task_id: str, context_id: str, run_id: str, decision: dict
    ) -> dict:
        """Resume the checkout checkpoint with the embedded card's result."""
        return await lifecycle.resume_checkout(
            handle(task_id, context_id, run_id),
            CheckoutDecision.model_validate(decision),
        )
```

Add `FunctionTool(verifund_checkout)` to the tool list and extend the system prompt:

```
- If hitl.tool is request_verifund_paypal_checkout, call that frontend tool
  with hitl.args unchanged and wait for the card.
- When the card returns, call verifund_checkout with the exact structured
  result. Never call verifund_evidence_review immediately after the card;
  the checkout result already resumes the task.
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_orchestrator_verifund.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(orchestrator): render and resume the checkout HITL`.

---

### Task 9: Next.js PayPal singleton

**Files:**
- Create: `apps/console/lib/paypal.ts`
- Test: `apps/console/tests/lib/paypal.test.ts`

- [ ] **Step 1: Failing test** mocking `@paypal/paypal-server-sdk`: `createPayPalOrder("3400.00", "USD", "key")` calls `createOrder` with the expected body and `paypalRequestId`, and throws when the result has no id.
- [ ] **Step 2: Implement**

```ts
import {
  Client,
  Environment,
  OrdersController,
  CheckoutPaymentIntent,
} from "@paypal/paypal-server-sdk";

const paypalClient = new Client({
  clientCredentialsAuthCredentials: {
    oAuthClientId: process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID!,
    oAuthClientSecret: process.env.PAYPAL_CLIENT_SECRET!,
  },
  environment:
    process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT === "production"
      ? Environment.Production
      : Environment.Sandbox,
});

const ordersController = new OrdersController(paypalClient);

export async function createPayPalOrder(
  amount: string,
  currency: string,
  idempotencyKey: string,
) {
  const { result } = await ordersController.createOrder({
    body: {
      intent: CheckoutPaymentIntent.Capture,
      purchaseUnits: [{ amount: { currencyCode: currency, value: amount } }],
    },
    paypalRequestId: idempotencyKey,
  });
  if (!result.id) throw new Error("PayPal order creation failed: missing order ID");
  return result.id;
}

export async function capturePayPalOrder(orderId: string, idempotencyKey: string) {
  const { result } = await ordersController.captureOrder({
    id: orderId,
    paypalRequestId: idempotencyKey,
  });
  const capture = (result as any).purchaseUnits?.[0]?.payments?.captures?.[0];
  if (!capture?.id) throw new Error("PayPal capture failed: missing capture ID");
  return {
    captureId: capture.id as string,
    status: capture.status as string,
    amountCents: Math.round(Number(capture.amount.value) * 100),
    currency: capture.amount.currencyCode as string,
  };
}
```

- [ ] **Step 3: Run** the test → PASS; commit `feat(console): add PayPal server SDK singleton`.

---

### Task 10: Next.js server actions

**Files:**
- Create: `apps/console/app/actions.ts`
- Test: `apps/console/tests/app/actions.test.ts`

**Interfaces:**
- `createOrderAction({ transactionId, expiresAt? }) -> { id }` — amount comes from
  `funding/prepare`, the order is attached before returning, and an existing
  `provider_order_id` is reused only while the deadline is live.
- `captureOrderAction({ transactionId, orderId }) -> { orderId, captureId, status, amountCents, currency, settlementState }`.
- `pollFundingAction({ transactionId }) -> { state, funding }`.

- [ ] **Step 1: Failing tests** with mocked `@/lib/paypal` and `@/lib/control-plane-proxy`:
  create calls prepare before create, uses the prepared amount (ignoring any amount in
  the input), attaches before returning, reuses an attached order while the deadline is
  live, creates a new attempt after the deadline, and parses non-OK responses into a
  thrown error; capture uses the attempt-scoped key and refreshes; poll returns the
  projection.
- [ ] **Step 2: Implement**

```ts
"use server";

import { capturePayPalOrder, createPayPalOrder } from "@/lib/paypal";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

async function controlPlane<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await controlPlaneJson(path, init);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.error ?? `Control plane responded ${response.status}`);
  }
  return body as T;
}

type FundingSession = {
  amount_cents: number;
  currency: string;
  order_attempt: number;
  provider_order_id: string | null;
};

async function prepareFunding(transactionId: string) {
  return controlPlane<FundingSession>(
    `/transactions/${transactionId}/funding/prepare`,
    { method: "POST" },
  );
}

function deadlinePassed(expiresAt?: string) {
  if (!expiresAt) return false;
  return Date.parse(expiresAt) <= Date.now();
}

export async function createOrderAction(input: {
  transactionId: string;
  expiresAt?: string;
}) {
  const session = await prepareFunding(input.transactionId);
  if (session.provider_order_id && !deadlinePassed(input.expiresAt)) {
    return { id: session.provider_order_id };
  }

  const attempt = (session.order_attempt ?? 0) + 1;
  const orderId = await createPayPalOrder(
    (session.amount_cents / 100).toFixed(2),
    session.currency,
    `fund:${input.transactionId}:embedded:v${attempt}`,
  );
  await controlPlane(`/transactions/${input.transactionId}/funding/attach-order`, {
    method: "POST",
    body: JSON.stringify({ order_id: orderId }),
    headers: { "content-type": "application/json" },
  });
  return { id: orderId };
}

export async function captureOrderAction(input: {
  transactionId: string;
  orderId: string;
}) {
  const session = await prepareFunding(input.transactionId);
  const attempt = Math.max(session.order_attempt ?? 0, 1);
  const capture = await capturePayPalOrder(
    input.orderId,
    `capture:${input.transactionId}:v${attempt}`,
  );
  const projection = await controlPlane<{ state: string; funding?: unknown }>(
    `/transactions/${input.transactionId}/funding/refresh`,
    { method: "POST" },
  );
  return {
    ...capture,
    orderId: input.orderId,
    settlementState: projection.state,
  };
}

export async function pollFundingAction(input: { transactionId: string }) {
  return controlPlane<{ state: string; funding?: unknown }>(
    `/transactions/${input.transactionId}/funding/refresh`,
    { method: "POST" },
  );
}
```

Note: `order_attempt` is part of the prepare response (Task 2). It is `0` before the
first attach and equals the attached order's attempt afterwards, which is why create
uses `order_attempt + 1` and capture uses the already-attached attempt.

- [ ] **Step 3: Run** the action tests → PASS; commit `feat(console): add PayPal server actions`.

---

### Task 11: `PayPalCheckoutCard`

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx`
- Test: `apps/console/tests/features/chat/paypal-checkout-card.test.tsx`

- [ ] **Step 1: Failing tests** with mocked action modules and a stubbed
  `@paypal/react-paypal-js/sdk-v6` (provider + button): renders amount/currency/status;
  `createOrder` calls `createOrderAction` and returns `{ orderId }`; `onApprove`
  responds `completed` with the projection; a `PENDING` capture shows "confirming
  payment" and polls `pollFundingAction` before responding; `onCancel` responds
  `canceled`; a provider error shows the fallback and the fallback click responds
  `{ status: "fallback" }`; the button is disabled during a request.
- [ ] **Step 2: Implement** in `verifund-tools.tsx`:

```tsx
export const paypalCheckoutArgsSchema = z.object({
  transaction_id: z.string().min(1),
  amount_cents: z.number().int().positive(),
  currency: z.string().min(1),
  expires_at: z.string().optional(),
  message: z.string().default("Complete the PayPal checkout to fund this transaction."),
});

export function PayPalCheckoutCard({
  args,
  onDecision,
}: {
  args: z.infer<typeof paypalCheckoutArgsSchema>;
  onDecision: (decision: Record<string, unknown>) => void;
}) {
  const [phase, setPhase] = useState<"ready" | "pending" | "fallback" | "error">("ready");

  async function pollUntilFunded(transactionId: string) {
    setPhase("pending");
    for (let i = 0; i < 30; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      const projection = await pollFundingAction({ transactionId });
      if (projection.state === "FUNDED") return projection;
      if (projection.state !== "FUNDING_PENDING") break;
    }
    setPhase("error");
    throw new Error("Payment captured but settlement is still pending");
  }
  return (
    <PayPalProvider
      clientId={process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID!}
      environment={process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT as "sandbox" | "production"}
      components={["paypal-payments"]}
      pageType="checkout"
    >
      <PayPalOneTimePaymentButton
        presentationMode="auto"
        disabled={phase !== "ready"}
        createOrder={async () => {
          const { id } = await createOrderAction({
            transactionId: args.transaction_id,
            expiresAt: args.expires_at,
          });
          return { orderId: id };
        }}
        onApprove={async ({ orderId }) => {
          const result = await captureOrderAction({
            transactionId: args.transaction_id,
            orderId,
          });
          const projection =
            result.settlementState === "FUNDED"
              ? { transaction_id: args.transaction_id, state: "FUNDED" }
              : await pollUntilFunded(args.transaction_id);
          onDecision({
            status: "completed",
            transaction_id: args.transaction_id,
            order_id: result.orderId,
            capture_id: result.captureId,
            projection,
            idempotency_key: `checkout:${args.transaction_id}`,
          });
        }}
        onCancel={() => onDecision({ status: "canceled", canceled: true })}
        onError={() => setPhase("fallback")}
      />
    </PayPalProvider>
  );
}
```

- [ ] **Step 3: Run** the component tests → PASS; commit `feat(console): add PayPal checkout card`.

---

### Task 12: Register the HITL tool

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`
- Test: `apps/console/tests/features/chat/verifund-tools.test.tsx`

- [ ] **Step 1: Add** a `useHumanInTheLoop` registration next to the funding-approval
  one, with `name: "request_verifund_paypal_checkout"`, `agentId:
  "marketmesh_orchestrator"`, `available: verifundEnabled && verifundMode === "sandbox"`,
  `parameters: paypalCheckoutArgsSchema`, and a `render` that mounts
  `PayPalCheckoutCard` when `status === "executing"` and a settlement note when
  `status === "complete"`. Call `onVerifundAction?.()` after `respond`.
- [ ] **Step 2: Update tests** to assert the tool is registered in sandbox mode, absent in
  fake mode, and that a completed render shows the settlement state.
- [ ] **Step 3: Run** `pnpm --dir apps/console test -- verifund-tools` → PASS;
  commit `feat(console): register the PayPal checkout HITL`.

---

### Task 13: Env, docs, and end-to-end checks

**Files:**
- Modify: `.env.example`
- Modify: `docs/verifund-paypal-sandbox.md`
- Modify: `apps/console/package.json` only if a script is needed (no new deps)
- Test: existing scripts

- [ ] **Step 1: Document env vars** — `NEXT_PUBLIC_PAYPAL_CLIENT_ID`,
  `NEXT_PUBLIC_PAYPAL_ENVIRONMENT`, server-only `PAYPAL_CLIENT_SECRET`, and the new
  `VERIFUND_CHECKOUT_MODE=redirect|embedded` (default `redirect`), including the rule
  that `NEXT_PUBLIC_PAYPAL_CLIENT_ID` must equal `PAYPAL_CLIENT_ID`.
- [ ] **Step 2: Add a preflight assertion** (in `scripts/verifund_sandbox_preflight.py`)
  that the two client ids match and that `PAYPAL_CLIENT_SECRET` is present when
  `VERIFUND_CHECKOUT_MODE=embedded`.
- [ ] **Step 3: Document the manual sandbox walkthrough** — approval → checkout card →
  popup → capture → refresh → purchase order — and the fallback path.
- [ ] **Step 4: Run** `make verifund-e2e` (fake mode) and `make verifund-preflight`;
  both must pass unchanged.
- [ ] **Step 5: Commit** `docs(verifund): document embedded PayPal checkout`.

---

## Self-review checklist

- Spec coverage: contracts/approval type, prepare, attach, refresh, capture key, buyer
  proxy, verifund graph, orchestrator tool+prompt, Next.js singleton, actions, card,
  registration, env/docs — every spec section has a task.
- Decisions: abandon → attach replacement after deadline/void (Tasks 3, 11); verifund
  agent owns prepare (Tasks 6, 7); mirror `fund()` checks (Task 2); cancel terminal and
  pending pauses (Tasks 7, 8, 11); SDK fallback to the redirect node (Tasks 7, 11).
- Prepare leaves the record `AGREED`; `attach` owns `AGREED -> FUNDING_PENDING`, so the
  redirect fallback's `/fund` call is still valid (Tasks 2, 3, 7).
- Attach happens at order creation, not after capture (Tasks 3, 10, 11).
- No browser-supplied amounts: Task 10 reads `prepare`.
- No `Response` returned from a server action: Task 10 parses every call.
- Type consistency: `amount_cents` (int, Python) / `amountCents` (number, TS);
  `order_attempt` drives both idempotency keys.

**Execution options:** Subagent-driven (recommended) or inline. Which approach?
