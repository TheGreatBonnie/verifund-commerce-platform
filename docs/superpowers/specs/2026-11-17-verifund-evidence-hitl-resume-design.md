# Verifund: orchestrator-driven evidence wait and resume

**Date:** 2026-11-17
**Status:** Proposed (awaiting review before implementation)

## 1. Problem

After PayPal funding completes, the verifund agent graph parks at the
`await_evidence` interrupt (`VerifundCheckpoint.EVIDENCE_PENDING`) and waits for
the seller to submit fulfillment evidence. Today nothing reliably drives that
graph forward when the seller finishes uploading:

- The orchestrator's `verifund_evidence_review` tool places the purchase order,
  then returns immediately with `status: working / checkpoint: evidence_pending`.
  It does not poll or resume at `EVIDENCE_PENDING`.
- `verifund.transaction.status` already contains the resume logic (the verifund
  agent's `VerifundAgentService._transaction_status`, `service.py:311-320`): when
  the checkpoint is a polled checkpoint (`evidence_pending` is one) and the
  projection is ready, it calls
  `graph.ainvoke(Command(resume={"projection": projection}), config)` using
  `thread_id = context_id`. But that logic only runs when something calls status.
- The chat therefore surfaces a terminal-looking "working" result. The seller
  uploads evidence in a separate console area, and the buyer's chat does not
  automatically advance to `RELEASE_APPROVAL_REQUIRED`.

Goal: make the orchestrator treat evidence submission like its other HITLs —
the chat waits visibly, refreshes status, and resumes the verifund graph through
the existing status A2A skill once the projection is ready, then presents the
release-approval HITL.

## 2. Goals / non-goals

### Goals
1. The verifund graph resumes from `await_evidence` when seller evidence is
   ready, using the existing `Command(resume=...)` path — no new graph node.
2. The orchestrator drives the resume by calling its existing `verifund_status`
   tool (the `verifund.transaction.status` A2A skill), consistent with how it
   handles funding / checkout / release HITLs.
3. The chat shows a genuine "waiting for seller evidence" state and advances to
   the release HITL once the checkpoint changes.
4. The spec documents exactly what evidence the seller must provide.

### Non-goals
- No new control-plane A2A client or new Render env vars. The control plane has
  no verifund-agent A2A config, and its `TransactionRecord` has `run_id` but no
  `context_id` (the graph's `thread_id`). Adding that is unnecessary.
- No changes to the verifund agent graph or its checkpointer. The
  `await_evidence` node already exists (`graph.py:867`, wired `1043-1044`).
- No blocking in-tool poll at `EVIDENCE_PENDING` (unbounded latency, serverless
  timeouts). Evidence latency is a human action, not a fast payment capture.
- No conversion of the ADK orchestrator to LangGraph.

## 3. What the seller must provide (evidence catalog)

Evidence is addressed by **`requirement_id`** (not the deprecated `kind`). The
authoritative catalog is `project_requirements()` in
`packages/verifund_contracts/verifund_contracts/terms.py`; agreements carry their
own `requirements[]`, so the live agreement is the source of truth. The laptop
template (`electronics.laptop.refurbished`) is the canonical example.

### 3.1 Seller-owned **required** requirements (must all verify to reach `RELEASE_PERMITTED`)

| `requirement_id` | What the seller provides | Source / format | Checks |
|---|---|---|---|
| `serial` | Full serial number plus a clear photo of the physical serial label (and system-info record where available) | file · image (`jpeg`/`png`/`webp`) | `serial_readable` |
| `provenance` | Photo of the device showing the one-time, transaction-specific Verifund challenge code | file · image | `challenge_code` matches active challenge |
| `product_photos` | Multi-angle baseline condition photos — **min 7**, views: front, back, left, right, keyboard, screen, underside, serial | file · images | `views_cover` |
| `condition_declaration` | Structured condition, lock and accessory declaration (locks disabled, battery health declared, defects disclosed) | **declaration** (declare endpoint, not a file) | `locks_disabled`, `battery_health_declared` |
| `hardware` | Diagnostic report matching agreed specs | file · diagnostic formats | `ram_gte_32gb` (32), `storage_gte_1tb` (1024 GB) |
| `battery` | Battery health / cycle report | file · diagnostic formats | `battery_health_pct` ≥ 80% |
| `warranty` | Warranty / coverage evidence | file · diagnostic formats | `warranty_gte_90_days` (90) |
| `packaging` | Photos: unit with serial, inside box, sealed box with label — **min 3**, views: `unit_with_serial`, `inside_box`, `sealed_with_label` | file · images | `views_cover` |
| `shipping` | Carrier and tracking reference | **reference** (not a file) | `carrier_present`, `tracking_present` |
| `invoice` | Seller invoice for the transaction | file · diagnostic formats | `invoice_present` |

### 3.2 Seller-owned **optional**
| `requirement_id` | What the seller provides | Source | Check |
|---|---|---|---|
| `insurance_confirmation` | Shipping-insurance coverage when required by value/policy | file · diagnostic formats | `insured_value_sufficient` |

### 3.3 System-owned (seller does **not** upload)
| `requirement_id` | Source |
|---|---|
| `carrier_acceptance` | Carrier acceptance event (system-sourced) |
| `delivery_confirmation` | Carrier delivery event / proof of delivery (system-sourced) |

### 3.4 Submission rules and gate
- Files: multipart upload with `requirement_id`, within `accepted_formats`, ≤
  `VERIFUND_MAX_EVIDENCE_BYTES` (25 MB default). `kind=` is rejected (422).
- Declarations (`source: "declaration"`) use
  `POST /transactions/{transaction_id}/requirements/{requirement_id}/declare`.
- References (`source: "reference"`) carry a reference value (carrier + tracking),
  not a file.
- Uploaded files are **not** automatically approved. Per requirement status
  (`NOT_SUBMITTED → SUBMITTED → PROCESSING → VERIFIED/REJECTED/NEEDS_REVIEW`),
  checks run against the observed value.
- Rollup (`policy.py`): any REVIEW → `REVIEW_REQUIRED`; all PASS →
  `RELEASE_PERMITTED`; required seller-owned NOT_SUBMITTED before deadline →
  pending. `await_evidence` accepts `RELEASE_PERMITTED` **or** `REVIEW_REQUIRED`;
  anything else keeps the checkpoint at `EVIDENCE_PENDING`.
- Therefore the agents proceed when all required seller-owned requirements are
  verified (or an inconclusive result has been routed to review).

## 4. Design

### 4.1 Resume trigger (orchestrator-owned)
The orchestrator already has `verifund_status` → `VerifundLifecycle.status()` →
`VerifundA2AClient.status()`, which dispatches the `verifund.transaction.status`
skill over A2A to the verifund agent. The verifund agent's `_transaction_status`
checks `pending in POLLED_CHECKPOINTS` and readiness via `_poll_is_ready`, then
issues `Command(resume={"projection": projection})`. No backend change is needed:
the status call *is* the resume trigger.

### 4.2 Orchestrator instruction / tool behavior (`apps/orchestrator_agent/orchestrator_agent/agent.py`)
- Extend `MARKETMESH_ORCHESTRATOR_INSTRUCTION`: when the latest tool result has
  `checkpoint == "evidence_pending"`, treat it as a wait state (not success).
  On a refresh, call `verifund_status` with the exact `task_id`, `context_id`,
  `run_id`; the verifund agent resumes the graph when the projection is ready.
  When the result shows `RELEASE_APPROVAL_REQUIRED`, render the
  `request_verifund_release_approval` HITL and call `verifund_release` with the
  structured decision, then `verifund_receipt`.
- Correct the `verifund_evidence_review` docstring (currently claims to "poll
  funding, evidence, or release"; it places the PO then returns).

### 4.3 Console chat card (`apps/console/features/chat/chat.tsx`)
- In the `verifund_evidence_review` / `verifund_status` renderers, when the
  parsed result has `checkpoint === "evidence_pending"` (or status `working`
  with that checkpoint), show a "waiting for seller evidence" state.
- Use the canonical CopilotKit v2 programmatic-control pattern (already imported
  in this file): `useAgent({ agentId: "marketmesh_orchestrator" })` gives `agent`;
  `useCopilotKit()` gives `copilotkit`. On the poll tick, guard on
  `agent.isRunning`, then `agent.addMessage({ id, role: "user", content:
  "Check Verifund status" })` and `await copilotkit.runAgent({ agent })`. The LLM
  then calls `verifund_status`, whose A2A status skill resumes the graph.
  (`useRenderTool` is render-only, so the polling effect lives in the component
  scope, not in the render callback.)
- Stop the interval when the checkpoint becomes `release_approval_required` /
  `completed`, on unmount, or on error. Avoid duplicate overlapping refreshes.

### 4.4 Data flow
```
seller uploads evidence (control plane)
  → verifund projection becomes RELEASE_PERMITTED / REVIEW_REQUIRED
  → chat card detects evidence_pending, polls verifund_status
  → orchestrator verifund_status → A2A verifund.transaction.status
  → verifund agent _transaction_status: _poll_is_ready == true
  → graph.ainvoke(Command(resume={"projection": ...}), thread_id=context_id)
  → await_evidence returns → await_release interrupt
  → chat view shows RELEASE_APPROVAL_REQUIRED HITL → verifund_release
```

## 5. Error handling
- If projection is not ready, `verifund_status` returns the pending payload;
  polling continues. No error is raised.
- If status/resume fails, stop polling and show the error; do not fabricate a
  release or receipt.
- A rejected release remains a manual-review outcome.
- Keep exact `task_id` / `context_id` / `run_id` from tool results; never invent
  HITL arguments.

## 6. Testing (TDD, red → green)
- Orchestrator: instruction contains the evidence-wait → status-refresh → release
  rule; `verifund_status` tool still dispatches status skill (characterization).
- Verifund agent: `_poll_is_ready` returns true for RELEASE_PERMITTED and
  REVIEW_REQUIRED at `evidence_pending`, false otherwise; `await_evidence` rejects
  a mismatched/unready projection (existing tests preserved).
- Console: evidence card shows waiting state for `evidence_pending`; polling
  starts for that checkpoint and stops on `release_approval_required`/unmount.
- Run targeted suites, then `graphify update .`.

## 7. Risks / mitigations
- **Polling noise / duplicate resumes:** the graph resume is idempotent via
  checkpoint state (`_pending` returns None once past the interrupt); guard the
  UI interval against overlap and clear it on checkpoint change.
- **Context id stability:** status calls reuse the handle from prior tool
  results; no new identifier plumbing.
- **Acceptance clock:** `RELEASE_PERMITTED` is subject to the buyer inspection
  deadline; if not yet permitted the card stays in the wait state.
