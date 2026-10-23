# Orchestrator-Mediated Buyer–Seller (Tasks 1–4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the buyer's direct seller calls and parallel fan-out with the mediated serial path proven in Task 0, harden orchestrator mediation, lock in approval/ordering regression coverage, and remove the legacy direct path.

**Architecture:** Buyer graph is the commerce authority and owns the serial seller order. Every seller interaction (RFQ, counter, accept, order) is a distinct `seller_call` interrupt carrying a thin wrapper over existing commerce contracts. The orchestrator's `FunctionTool` (proven in Task 0) makes the single A2A call by agent card and resumes the same buyer checkpoint via `Command(resume=...)`. Approval keeps its independent `order_approval` interrupt. Seriality is structural.

**Tech Stack:** Python 3.12, LangGraph 1.2.16, a2a-sdk 1.2.3, google-adk 1.39.1, FastAPI/uvicorn, pytest + httpx.

**Spec:** `docs/superpowers/specs/2026-10-23-orchestrator-mediated-buyer-seller.md`

**Prerequisite:** Task 0 feasibility result recorded as PASS in the spec (done 2026-10-23). Plan A: `docs/superpowers/plans/2026-10-23-orchestrator-feasibility-gate.md`.

## Global Constraints

- Buyer must not call seller endpoints directly after migration; orchestrator owns seller-call sequencing.
- At most one seller A2A request in flight per buyer run (structural, via pause/resume).
- Seller request/response round-trips semantically (assert semantic equality, not byte identity).
- A2A agent cards + A2A SDK only; no REST endpoints, custom middleware, or guessed APIs.
- Approval remains a distinct pause/resume path; cannot be mistaken for a seller call.
- Reuse existing commerce contracts and A2A helpers; no duplicate models.
- LangGraph `interrupt()` restarts the node on resume; pre-interrupt work must be idempotent.
- Fan-out (`Send`) and direct client usage must be removed or made unreachable for mediated mode.

---

## Task 1: Buyer graph contract (mediated serial negotiation)

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py` (make mediated path the default; remove `fan_out_sellers`/`Send` usage; make `negotiate_seller` mediated)
- Modify: `apps/buyer_agent/buyer_agent/a2a_client.py` (no change needed; direct usage removed from graph)
- Test: `tests/integration/test_mediated_graph.py`, `tests/integration/test_buyer_graph.py`

**Interfaces:**
- Consumes: `commerce_core.contracts` (RFQ, CounterOffer, AcceptOffer, Offer, Mandate, ...), `buyer_agent.planner`.
- Produces: `build_buyer_graph(...)` now runs the mediated serial negotiation; interrupt values carry `reason: "seller_call"` with `kind` in {`rfq`, `counter`, `accept`, `order`}.

- [ ] **Step 1: Remove fan-out and direct negotiation node**

In `apps/buyer_agent/buyer_agent/graph.py`, delete `fan_out_sellers` and the `prepare_fanout`/`Send` import usage. Remove the `negotiate_seller` function's direct `A2ASellerSession` calls. Replace the graph wiring so that after `plan_sourcing` the graph enters the mediated serial loop (reuse `_mediated_select`/`_mediated_pause`/`_mediated_apply` from Plan A, extended below).

- [ ] **Step 2: Extend mediated negotiation to counters and accept**

Replace the single RFQ pause with a loop per seller that pauses for each seller call. Add `kind`-aware pause payloads:

```python
async def _mediated_negotiate_seller(state, config):
    # RFQ
    ... pause kind="rfq" ...
    # resume -> initial offer
    # counter rounds (up to 3) mediated
    for round_number in range(1, 4):
        if final_offer_received:
            break
        ... pause kind="counter" with CounterOffer ...
        # resume -> counter offer
    # accept
    ... pause kind="accept" with AcceptOffer ...
    # resume -> accepted
    return {"offers": [final_offer], "negotiations": [record]}
```

Each pause uses `interrupt({... "reason": "seller_call", "kind": ..., "seller_id": ..., "request": wrap_payload(...), ...})`. Pre-interrupt work (RFQ/counter construction, budget guardrail) stays idempotent.

- [ ] **Step 3: Mediate post-approval order**

In `place_order`, replace direct `open_session`/`send_order` with a `seller_call` pause (`kind="order"`, request = `wrap_payload("purchase_order", po)`). On resume, apply the returned order to state.

- [ ] **Step 4: Make mediated graph the default**

Rename `build_mediated_buyer_graph` logic into `build_buyer_graph` (or make `build_buyer_graph` delegate to it). Remove `build_mediated_buyer_graph` alias after migration, or keep as deprecated. Update `server.py` to drop the `mediated` flag (always mediated).

- [ ] **Step 5: Update tests**

Update `tests/integration/test_buyer_graph.py` and `tests/integration/test_mediated_graph.py` to assert: snapshot at pause shows `reason == "seller_call"`; after each resume checkpoint identity preserved; no direct seller-client calls (`services.a2a` call counts stay 0 in mediated runs). Keep `test_approval.py` passing (approval reason unchanged).

- [ ] **Step 6: Run targeted tests**

Run: `uv run pytest tests/integration/test_buyer_graph.py tests/integration/test_mediated_graph.py tests/integration/test_approval.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/graph.py apps/buyer_agent/buyer_agent/server.py tests/integration/test_buyer_graph.py tests/integration/test_mediated_graph.py
git commit -m "feat: migrate buyer graph to mediated serial seller calls"
```

---

## Task 2: Orchestrator mediation hardening

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/mediation.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Test: `tests/unit/test_orchestrator_mediation.py`, `tests/integration/test_mediation_gate.py`

**Interfaces:**
- `mediate_seller_call(...)` returns `{"resumed": True, "seller_result": {...}}` on success, `{"error": ..., "retryable": bool}` on failure; handles timeouts without losing buyer checkpoint.

- [ ] **Step 1: Seller error/timeout handling**

Wrap the seller A2A call in a timeout (e.g. 60s) and on failure return `{"error": str(exc), "retryable": True}` without resuming (or resume with an error result). Ensure the buyer checkpoint remains resumable. Add a `seller_error` result path in the buyer graph (record `NegotiationRecord(status="error")`, continue to next seller).

- [ ] **Step 2: One-at-a-time enforcement test**

Add a test that drives two seller pauses and asserts the second cannot start until the first resumes (structural: graph `next` is `pause_seller_call` with no concurrent invocation).

- [ ] **Step 3: AG-UI event verification**

Extend `test_mediation_gate.py` to assert the buyer A2A stream contains both the `seller_call_required` INPUT_REQUIRED and the subsequent completed/status events (already partially covered). Add orchestrator AG-UI smoke test if feasible.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_orchestrator_mediation.py tests/integration/test_mediation_gate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/mediation.py tests/unit/test_orchestrator_mediation.py tests/integration/test_mediation_gate.py
git commit -m "feat: harden orchestrator mediation (errors, timeouts, events)"
```

---

## Task 3: Approval and ordering regression coverage

**Files:**
- Test: `tests/integration/test_approval.py` (extend)
- Test: `tests/integration/test_ordering.py` (new)

**Interfaces:**
- Reuse `normalize_approval`, `await_approval`, `approval_route`.

- [ ] **Step 1: Rejection places no order**

Extend `test_approval.py` with a mediated-mode case: rejection -> no order call, no accept call, negotiations cancelled, stage rejected. (Already covered for legacy; re-run under mediated mode.)

- [ ] **Step 2: Approval resumes ordering only after decision recorded**

Add `tests/integration/test_ordering.py`: approval -> place_order runs -> order created; verify the order uses the mediated `order` seller call (buyer `services.a2a` order count stays 0).

- [ ] **Step 3: Payload non-interchangeability**

Add tests: a `seller_call` INPUT_REQUIRED payload resumed with an approval-shaped payload does not place an order; an approval payload cannot be interpreted as a seller result. Assert the executor leaves state unchanged or errors cleanly.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_approval.py tests/integration/test_ordering.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_approval.py tests/integration/test_ordering.py
git commit -m "test: approval and ordering regression coverage (mediated)"
```

---

## Task 4: Remove legacy path and verify

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py` (remove direct client usage, `A2ASellerSession` import if unused)
- Modify: `apps/buyer_agent/buyer_agent/server.py` (remove `mediated` flag)
- Modify: `apps/buyer_agent/buyer_agent/a2a_client.py` (keep as seller-facing helper only if still used by orchestrator; otherwise mark unused)
- Test: full suite + console typecheck

- [ ] **Step 1: Remove direct buyer-to-seller client calls from graph**

Delete any remaining `services.a2a.open_session` calls in `graph.py`. Ensure `grep "open_session" apps/buyer_agent/buyer_agent/graph.py` returns nothing.

- [ ] **Step 2: Remove the `mediated` flag**

`create_app` always uses the mediated graph. Remove the parameter (or keep deprecated alias). Update tests/callers.

- [ ] **Step 3: Run targeted tests**

Run: `uv run pytest tests/integration/test_buyer_graph.py tests/integration/test_buyer_server.py tests/integration/test_approval.py tests/integration/test_mediation_gate.py tests/unit/test_buyer_executor_mediated.py -q`
Expected: PASS

- [ ] **Step 4: Run full Python suite**

Run: `uv run pytest -q`
Expected: 57+ tests pass, no regressions

- [ ] **Step 5: Console typecheck + build**

Run: `cd apps/console && npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 6: Coherence check**

Confirm trace, negotiation ledger, and chat display remain coherent (inspect a run's trace store output; verify seller_call events appear). Document any follow-ups.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: remove legacy direct buyer-seller path; verify mediated flow"
```

---

## Execution Handoff

Plan B ready. Recommended: subagent-driven (fresh subagent per task) given the migration touches the core graph. Inline execution also acceptable.

**STOP if** any mediated seller call cannot be made via package-supported APIs (revisit Task 0 fail condition).

After Plan B completes, run the full validation from the spec's Phase 6 (ruff, pytest, typecheck, build, docker compose config, dev stack smoke, Playwright E2E).
