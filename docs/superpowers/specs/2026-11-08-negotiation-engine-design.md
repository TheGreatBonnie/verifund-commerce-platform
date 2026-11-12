# Negotiation Engine Design (MarketMesh / Verifund A2A)

**Date:** 2026-11-08  
**Status:** Approved design (brainstormed), pending spec review  
**Scope:** `verifund-a2a/` — Buyer Agent, Seller Agent, `commerce_core`, A2A negotiation payloads/artifacts, Verifund settlement binding  
**Inputs:** `docs/superpowers/specs/ai-agents-negotiatiation-skills.md` (capability taxonomy), existing implementation in `apps/seller_agent/seller_agent/graph.py`, `apps/buyer_agent/buyer_agent/{graph,planner,policies,agreement_service}.py`, `packages/commerce_core/commerce_core/contracts.py`, `packages/verifund_contracts/*`, mediated 1:N A2A + settlement flow.

## Summary

Introduce a **Negotiation Engine** as explicit, testable modules while preserving current behavior (**Approach A: extract shared core + wrap existing graphs**).

- **Shared deterministic core**: `packages/commerce_core/commerce_core/negotiation/` (pure; no LLM/network/DB/LangGraph).
- **Thin adapters**: `apps/seller_agent/seller_agent/engine.py`, `apps/buyer_agent/buyer_agent/engine_session.py` (and optional coordinator extraction) called by existing LangGraph nodes.
- **Orchestration unchanged in shape**: LangGraph state/checkpointing, mediated `interrupt` A2A flow, 1:N buyer coordination, and Verifund settlement lifecycle remain behaviorally compatible.

## Non-negotiable invariants

1. **LLM proposes; deterministic policy authorizes.** Planner output is a candidate. `concessions`/`mandate_policy`/validators authorize. Invalid/unsafe → 1–2 retries → scripted deterministic fallback. LLM never authorizes spend, floor exceptions, agreement lock, or payment.
2. **Agreement ≠ payment.** `AcceptOffer`/commercial acceptance expresses intent. **Commitment = canonical Verifund agreement lock + required approvals/reviews + payment/funding authorization** per control-plane lifecycle.
3. **No budget/floor leakage; untrusted inbound content.** Buyer `max_total_cents` never appears in seller-facing RFQ/messages/artifacts/logs. Counterparty prose/fields are untrusted data (prompt-injection resistant); never executed as instructions.
4. **Deterministic trust boundary on every inbound offer/counter/accept-relevant payload.** Verify seller↔validated Agent Card, `request_id`/task binding, SKU, recomputed line/subtotal/total, `valid_until`, version/round/lineage; sanitize untrusted claims (e.g., rating/cert) using validated sources. Reject on mismatch.
5. **Money in integer cents; totals recomputed.** `*_cents` integers only. `total_cents = subtotal_cents + shipping_cents + tax_cents + fees_cents`. Never trust counterparty or LLM arithmetic.
6. **1:N safety.** Per-seller isolated session state/history; global timeout; rank only trusted, eligible, non-expired finals; deterministic winner selection. One seller’s deadlock/timeout must not block others.
7. **Mediated/settlement compatibility.** `interrupt` reasons/payload-resume contracts (`seller_call`, `agreement_create_required`, `seller_review_required`), `thread_id`/checkpointing, trace decisions, and `agreement_mismatch_reason` hard gate remain compatible. Additive fields only, with tolerant readers.

## Section 1 — Scope & invariants

### 1.1 Goal
Formalize negotiation semantics into reusable engines without destabilizing A2A/settlement behavior.

### 1.2 In scope
- RFQ → offer → counter → accept/reject/clarify/escalate, bounded by rounds/time.
- Deterministic guardrails: trust/binding, cents-total recomputation, `valid_until` expiry, version/idempotency, SKU/request/seller binding.
- Concession/trade-off/feasibility (price, `shipping_cents`, `warranty_months`, `delivery_days`, `split_shipment`; extensible).
- Deadlock detection: `continue | propose_alternative | escalate_human | terminate(reason)`.
- Versioned A2A business payload/artifact schema registry + task-state mapping.
- Buyer 1:N per-seller session rules + global coordination boundaries.
- Verifund binding: canonical lock, mismatch hard gate, review/precheck/payment separation.

### 1.3 Out of scope (this phase)
- Replacing LangGraph or mediated `interrupt` architecture; Approach B big-bang rewrite; Approach C sidecar service.
- New payment rails, real fulfillment, or control-plane API changes (consume existing binding fields).
- ML-trained negotiation strategy or sentiment authority (use observable signals).
- Full FX/tax jurisdiction engine (define hooks/fields; deterministic handling required before payment auth).

### 1.4 Success criteria
- Guardrail matrix passes with scripted planners in CI (budget leak, floor, totals, expiry, stale version/hash/idempotency, SKU/request/seller mismatch).
- Characterization baseline: equivalent externally visible outcomes for current scripted seller/buyer scenarios.
- Decisions traceable: `source, action, rationale, fallback_used, seller_id, round`.
- Core unit tests run with no LangGraph/A2A/network dependencies.

## Section 2 — Contracts & schemas

### 2.1 Design stance
- **Evolve, don’t break** `commerce_core.contracts` / `verifund_contracts`. Add optional/defaulted fields for wire compatibility; add new models under `commerce_core.negotiation.schemas` and map to/from existing `RFQ/Offer/CounterOffer/AcceptOffer/PurchaseOrderRequest/Order`.
- Integer cents only; explicit `currency` (default `USD`).
- Negotiable/committable payloads carry correlation + versioning: `run_id/request_id`, `offer_id`, `round`/`negotiation_round`, `task_id/context_id` where applicable, settlement `agreement_version/hash` where applicable.

### 2.2 Core negotiation models (`commerce_core.negotiation`)
```python
PartyRole = "buyer" | "seller"
NegotiationSessionId = {run_id, counterparty_id, request_id}

NegotiationContext:
  session: NegotiationSessionId
  role: PartyRole
  counterparty: {id, name, card_url?, validated_rating?, validated_cert?}
  mandate: MandateView        # seller-facing view OMITS max_total_cents
  policy: PolicyView
  round: int                  # 1-based
  max_rounds: int
  now_utc: datetime
  response_deadline_utc: datetime | None
  history: list[NegotiationTurn]
  concession_budget: ConcessionBudget
  state: active|input_required|accepted_intent|agreement_pending|terminal
  terminal_reason: accepted|rejected|expired|deadlocked|cancelled|failed|None

NegotiationTurn:
  turn_id, round, direction(in|out), kind, payload_ref/hash,
  offer_id?, total_cents?, valid_until?, decision_source?, fallback_used?

ConcessionBudget (local-only, deterministic):
  price: {min_unit_cents, max_unit_cents, allowed_targets?: list[int]}
  shipping_cents: {allowed: list[int]} | range
  warranty_months: {allowed: list[int]}
  delivery_days: {max: int} | {allowed: list[int]}
  split_shipment: bool
  non_negotiable: list[field]
```
`Mandate`/`max_total_cents` remain buyer-local; seller-facing views never include max budget.

### 2.3 Commerce payload alignment
| Payload | Canonical fields | Notes |
|---|---|---|
| `RFQ` | `schema_version, request_id, run_id, category, product_hint, product_sku?, quantity, required_by, constraints, preferences, message?` | `message` must pass budget-safety. Optional additive `response_by`/`expires_at`. |
| `Offer` | existing + validated `valid_until, round, binding_version, request_id, task_id/context_id?` | `Offer._validate_totals` pattern required. `tax_cents/fees_cents` explicit. Additive optional `parent_offer_id`/`supersedes_offer_id`. |
| `CounterOffer` | `schema_version, negotiation_round, target_unit_price_cents?, requested_changes, rationale, in_response_to_offer_id?` | **Typed `requested_changes`**: `warranty_months:int?`, `split_shipment:bool?`, `shipping_cents:int?`, `delivery_days:int?`; unknown keys rejected. Optional `idempotency_key`. |
| `AcceptOffer` | `offer_id, round, accepted_total_cents, accepted_by_buyer_task?, settlement_transaction_id?, agreement_hash?, settlement_token?` | Optional `idempotency_key`, `accepted_at`. Settlement fields required when enabled. |
| `PurchaseOrderRequest` | existing `idempotency_key, expected_total_cents, approval, settlement_*` | Idempotent; bind to accepted offer + agreement hash/version when applicable. |
| `commerce_error` | `code, message, retryable, details` | Codes: `invalid_request, unsupported_constraint, offer_expired, stale_version, binding_mismatch, below_floor, over_budget, out_of_stock, conflict, deadlocked, timeout`. |

### 2.4 A2A payload/artifact registry
Business events are **DataParts/Artifacts**, not A2A-native message types.
```python
PayloadSpec(name, schema_version, model, direction, task_states_allowed, terminal?)
```
Negotiation/commerce v1 names: `rfq, offer, counter_offer, accept_offer, purchase_order, order, commerce_error`. Settlement-aligned: `agreement` projection/review payloads (existing `verifund_contracts.a2a` shapes), optional `negotiation_history` artifact. Envelope concept (compatible with existing helpers): `{schema: "marketmesh/commerce/<name>@v1"|existing, payload: {...}, correlation: {run_id,request_id,offer_id?,round?,task_id?,context_id?}}`.

### 2.5 Idempotency, versioning, expiry
- Idempotency: `accept:{run_id}:{offer_id}:{round}`, `po:{run_id}:{offer_id}` (or explicit key). Same key+same bound payload ⇒ replay prior result; divergent ⇒ `conflict/stale_version`.
- Lineage: counter/accept reference `in_response_to_offer_id`/latest + `round`; reject stale/superseded.
- Expiry: `now_utc > valid_until` ⇒ `offer_expired` (not rankable/acceptable); default no grace.
- Settlement binding uses canonical `agreement_hash/version`.

### 2.6 Validation before emit/accept/rank
- Recompute subtotal/total; validate quantities/prices/addons/delivery/rounds.
- `currency` matches run; `request_id/seller_id/sku` bound to trusted context.
- `requested_changes` ⊆ typed allowlist and within `ConcessionBudget/AllowedMoves`.
- Buyer outbound text/messages pass budget-safety check.

## Section 3 — Shared deterministic core (`packages/commerce_core/commerce_core/negotiation/`)

**Pure/deterministic only:** no LLM, network, DB, or LangGraph. Apps inject I/O at edges.

| Module | Responsibility | Key API (conceptual) |
|---|---|---|
| `types.py` | Context/turn/action/decision/eval models | Pydantic/dataclass + enums |
| `events.py` | Typed inbound/outbound normalization | `parse_event`, `event_kind` |
| `schemas.py` | Versioned payload registry + envelope helpers | `REGISTRY`, `wrap/parse/migrate`, compatibility w/ existing helpers |
| `money.py` | Integer-cents invariants | `recompute_subtotal`, `recompute_total`, `validate_offer_totals` |
| `trust.py` | Trust boundary (generalizes buyer `_trusted_offer`) | `verify_offer_binding`→`TrustedOffer|Reject`, `sanitize_untrusted_claims` |
| `mandates.py` | Deterministic mandate/policy checks | `hard_constraint_failures`, `budget_allows` (local), `rfq_text_safe` |
| `concessions.py` | `AllowedMoves` + sole concession authority | `constrain_candidate`, allowed typed changes/targets |
| `tradeoff.py` | Bounded feasible alternatives | `generate_alternatives` (deterministic utility ordering) |
| `deadlock.py` | Observable-signal outcomes | `detect`→`continue|propose_alternative|escalate_human|terminate` |
| `artifacts.py` | Sanitized history/agreement-proposed payload builders | no secrets, no budget |

### 3.1 Trust checks (ingress)
1. `seller_id` matches validated Agent Card/provenance.
2. `request_id` (and task/context when present) matches session.
3. SKU/quantity bound (pinned SKU enforced).
4. Recompute line/subtotal/total; totals consistent.
5. `valid_until > now`; round/lineage (`in_response_to`/latest) consistent; stale → reject/conflict.
6. Sanitize untrusted claims using validated sources; never blindly trust seller authority fields.
7. Return `TrustedOffer` or `Reject(code, reason, retryable)`.

### 3.2 Concessions & deadlock
- `AllowedMoves` derived from policy/mandate + round + prior state (seller ladder/floor/max_rounds/warranty/split; buyer deterministic `counter_targets`, budget-local).
- `constrain_candidate` rejects unknown change keys, out-of-range values, non-negotiable changes, floor/budget violations, and illegal state transitions.
- Deadlock signals (defaults specified in implementation/tests): rounds exhausted, expired/deadline passed, no feasible overlap, no progress for `k` rounds. Use trade-offs before terminal where feasible; escalate when human guidance needed.

## Section 4 — Seller engine integration (`apps/seller_agent`)

### 4.1 Approach
Keep LangGraph topology and A2A/order behavior; wrap nodes via `seller_agent/engine.py` + `commerce_core.negotiation`. Nodes become adapters.

### 4.2 Node mapping
| Node | Engine role | Preserved behavior |
|---|---|---|
| `classify` | schema registry / event kind | unsupported schema → deterministic error |
| `prepare` | context + `AllowedMoves` from policy/stock/previous offer | allowed prices/warranties, round, split; typed unsupported changes rejected |
| `decide` | planner candidate → `constrain_candidate`; invalid → scripted fallback | no disallowed move emitted; `fallback_used` traced |
| `finalize_offer` | pricing/quote → validated `Offer` (totals, `valid_until`, lineage, status) → persist | `input_required` with structured offer |
| `accept_offer` | trust/binding to persisted offer, total/round/idempotency; settlement validation when enabled | **intent/binding only, not payment** |
| `reject_offer` | normalized `commerce_error` | terminal semantics |
| `order` | idempotent create + settlement validator | unchanged; no seller self-certified delivery evidence |

### 4.3 Planner boundary
`SellerDecision` structured/forbidden-extra. Engine validates allowed targets/warranties/floor/action coherence. 1–2 attempts then `ScriptedSellerPlanner`; if still unsafe/impossible → deterministic error.

### 4.4 State/persistence
`SellerState` additive only. Persist offers/rounds; optional sanitized `negotiation_history` artifact.

## Section 5 — Buyer 1:N engine integration (`apps/buyer_agent`)

### 5.1 Split
- `engine_session.py`: per-seller session logic (budget-safe RFQ, trust/eval, next action in `AllowedMoves`, accept/PO candidate builders, deadlock). No direct A2A.
- `engine_coordinator.py` (optional): 1:N scheduling/aggregation/global timeout/stop rules (phase 1 keeps sequential mediated).
- `planner.py`: LLM boundary (parse brief, compose RFQ, choose counter, explain award) — strict schemas, retries, fallback.
- `graph.py`: keeps mediated orchestration, `interrupt` I/O, checkpoint/thread/trace/settlement; delegates semantics.

### 5.2 Mediated loop
- RFQ: `session.build_rfq` + `rfq_text_safe`; budget never disclosed.
- Per resume (`_turn_from_resume` shape preserved/tolerant): `trust.verify_*` → `TrustedOffer`s only; deterministic hard constraints + utility signals; `next_action` constrained to allowed targets/typed changes; fallback to scripted (preserve `_choose_counter` safety). Counter targets deterministic, never budget-derived for disclosure.
- Phase 1 sequential mediated preserved; state isolated per seller to enable bounded parallelism later.

### 5.3 Ranking/approval
- Ranking only over trusted, eligible, non-expired finals (`rank_eligible_offers` authoritative). Planner explains only, budget-safe.
- Human approval `interrupt` + `normalize_approval` unchanged.

### 5.4 Settlement binding (no regression)
- `agreement_create_required` returns validated `AgreementProjection`; `agreement_mismatch_reason` is a **hard gate** (run/buyer/seller/offer/currency/amount/qty/shipping/delivery/warranty/returns/line items + recomputed total).
- Buyer/seller reviews bind `transaction_id + agreement_version + agreement_hash` (+ idempotency); `seller_decision_matches` semantics preserved; stale agreement cache synced post-review.
- Settlement-mode funded order path separate from off-mode `place_order`; plain A2A accept never authorizes payment.

## Section 6 — A2A & task lifecycle

### 6.1 Transport vs semantics
A2A 1.x JSON-RPC + SSE carries discovery/cards, tasks/messages/artifacts. Negotiation semantics are versioned business payloads in DataParts/Artifacts.

### 6.2 Discovery/cards
- Discovery: `/{seller_id}/.well-known/agent-card.json`; RPC `/{seller_id}/a2a`; tenant `agent_<seller_id>`.
- Seller advertises `commerce.negotiate` (or deliberate split) with supported schema versions. Buyer validates cards before use; cards are not authority.

### 6.3 Correlation
`run_id, request_id, task_id/context_id, offer_id, round, idempotency_key, transaction_id/agreement_version/hash` (settlement). Inbound accepted only when matching trusted session context.

### 6.4 Task/artifact mapping
- Working/input_required for RFQ/counter/clarification/alternative; terminal for accepted-intent handoff outcomes, rejected/expired/deadlocked/invalid/cancelled with normalized errors.
- Artifacts: per-round `offer/counter`, `order`, sanitized `negotiation_history` (no budget/secrets/tokens), `commerce_error`. Canonical agreement artifacts only from Verifund-authoritative flow.
- Exact status enum names follow the pinned A2A SDK/spec version; validate implementation against it.

### 6.5 Mediated interrupt contract (compatible)
- Outbound `seller_call`: `kind` in `rfq|counter|accept|order`, `seller_id`, `card_url`, wrapped `request`, `run_id/context_id/seller_task_id/seller_context_id`, message. Additive only.
- Resume normalized to `{offers, orders/order, task_id, context_id, error, text, state}` (tolerant).
- `agreement_create_required` / `seller_review_required` unchanged in meaning.

### 6.6 Ops & security
Idempotent retries only where safe; on ambiguous mutation timeout, query before retry. Enforce deadlines/`valid_until` and global timeout. Auth per existing model; seller tokens never exposed to console. Validate envelopes/models before engine logic; treat inbound as untrusted.

## Section 7 — Verifund / settlement binding

### 7.1 Authority
Negotiation engines/A2A: intent and local policy. Verifund/control plane: canonical agreement projection, reviews, funding/precheck/order reporting, settlement state machine. Human: approval/consent. **No payment authorization from negotiation acceptance.**

### 7.2 Lifecycle (hard gates)
Award → `agreement_create_required` → validate `AgreementProjection` binding → **`agreement_mismatch_reason` must be `None`** → buyer review (version/hash/idempotent) → seller review (`seller_decision_matches` semantics) → precheck → funding/order/fulfillment/settlement per control plane. Any mismatch/stale hash/version/malformed binding ⇒ reject/conflict, no state advance.

### 7.3 Rules
- Settlement-enabled accepts/POs require settlement binding validation; no bypass. Settlement runs don’t use plain off-mode funded order path.
- Idempotent agreement/review/accept/PO/order-report; divergent replay conflicts.
- Negotiation history/proposed artifacts are non-authoritative; Verifund projection authoritative.

## Section 8 — Testing, observability, rollout

### 8.1 Test pyramid
1. **Unit (`commerce_core.negotiation`)** — pure guardrails/money/trust/concessions/deadlock/tradeoff/schemas.
2. **Engine adapter unit** — seller/buyer session engines with fake ports + scripted planners.
3. **Characterization/integration** — existing LangGraph flows, scripted, fake A2A/settlement; baseline parity.
4. **Contract/A2A** — payload round-trips, registry, interrupt shapes.
5. **Settlement binding** — mismatch/hash/version/idempotency/conflict, bypass prevention.

### 8.2 Guardrail matrix (CI, scripted)
Budget/floor (incl. no budget leak), money/totals, trust/binding, version/expiry/idempotency, deadlock/1:N isolation, settlement binding & mode separation.

### 8.3 Observability
Trace `planner_decision/guardrail_rejected/protocol_error/trust_rejected/deadlock_detected/agreement_binding_rejected` with correlation ids and `fallback_used`. **No secrets, tokens, or `max_total_cents`** in traces/logs/artifacts. Sanitized `negotiation_history` artifact.

### 8.4 Rollout (A)
Phase 0 characterization baseline → Phase 1 core package → Phase 2 seller wrap → Phase 3 buyer session wrap → Phase 4 schema/artifacts/typed changes migration → Phase 5 hardening (bounded parallelism, richer trade-offs). Each phase additive; rollback by restoring adapter wiring if parity fails.

### 8.5 Risks
Interrupt/settlement regression (mitigate: characterization + additive/tolerant contracts), budget/floor leakage (safety checks + redaction), false trust (central `trust` + recompute), infinite negotiation (rounds/deadlines/deadlock), idempotency/version bugs (binding + conflict tests), schema drift (versioned registry + contract tests).

## Open implementation choices (defer to plan, not blockers to this spec)
- Keep single `commerce.negotiate` Card skill vs split skills (must declare supported schemas either way).
- Exact `marketmesh/commerce/*@v1` schema URI format aligned with existing `wrap_payload/parse_payload` conventions.
- `k`/threshold defaults for `no_progress` and global/per-seller timeouts (configurable, deterministic).
- Bounded parallel 1:N execution phase (after sequential parity proven).

## References (repo)
- `docs/superpowers/specs/ai-agents-negotiatiation-skills.md`
- `docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md`
- `docs/superpowers/specs/2026-10-27-verifund-control-plane-design.md`
- `docs/superpowers/specs/2026-10-30-verifund-agreement-management-design.md`
- `apps/seller_agent/seller_agent/{graph,card}.py`
- `apps/buyer_agent/buyer_agent/{graph,planner,policies,agreement_service}.py`
- `packages/commerce_core/commerce_core/contracts.py`
- `packages/verifund_contracts/` (agreement/review/A2A models)
