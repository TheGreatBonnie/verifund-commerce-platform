# Orchestrator-Mediated Buyer–Seller Communication

**Status:** Package-feasibility gate required before implementation.

## Goal

Route every buyer–seller request and response through the orchestrator, serially, while preserving structured payload meaning across the A2A handoff. The buyer remains the authority for sourcing, negotiation, ranking, and award decisions. Human approval remains mandatory before an order.

## Non-negotiable constraints

- The buyer must not call seller endpoints directly; the orchestrator owns seller-call sequencing.
- At most one seller A2A request may be in flight for a buyer run.
- Seller request and response data must round-trip semantically without being flattened into model-authored prose.
- All seller transport must use A2A agent cards and the A2A SDK; seller services do not expose the REST endpoints in the earlier plan sketch.
- Approval must remain a distinct pause and resume path and cannot be mistaken for a seller-call handoff.
- Do not add a custom middleware, guessed tool-registration API, REST shim, or parallel transport implementation to work around a package limitation.

## Verified package facts

Versions are from the current lockfiles and installed environment: `a2a-sdk` 1.2.3, LangGraph 1.2.16, `google-adk` 1.39.1, `@ag-ui/a2a-middleware` 0.0.6, and `@a2a-js/sdk` 0.2.5.

- LangGraph supports durable `interrupt()` / `Command(resume=...)` execution with a checkpointer. Returning a `pending_seller_call` state field alone does not pause the graph. On resume, the interrupted node restarts, so work before `interrupt()` must be safe to repeat.
- ADK 1.39.1 includes `RemoteA2aAgent`, but marks it experimental. ADK's A2A part converters can encode and reconstruct generic DataParts; verify semantic equality at the boundary rather than claiming protobuf-byte identity.
- The installed A2A middleware injects a fixed `send_message_to_a2a_agent` tool with a text `task` argument. It dispatches multiple tool calls with `Promise.all` and converts the reply to text or JSON text. It cannot by itself guarantee serial calls or typed DataPart preservation.
- The buyer graph currently fans out seller negotiations using LangGraph `Send`; that path must be replaced or made unreachable for the mediated mode before the no-direct-calls requirement is met.

## Task 0: Package-native feasibility gate

**Do not begin implementation tasks until this task passes.** Use the pinned packages and test fixtures; do not write a custom bridge to make the test pass.

1. Verify a package-supported composition using LangGraph interrupt/resume, ADK's A2A integration, and the A2A SDK. Pin the exact ADK version if its experimental `RemoteA2aAgent` is required.
   - Candidate mechanism to prove (design decision, 2026-10-23): **hybrid** — use `RemoteA2aAgent` (experimental) only for agent-card discovery; all seller transport goes through a documented ADK `FunctionTool` driving the A2A SDK client by agent card. Seriality is structural (buyer-graph pause), not middleware- or prompt-driven.
2. Drive a buyer A2A task to a seller-call pause, make one seller request through the orchestrator, then resume the same buyer checkpoint with the seller result.
3. Assert the original buyer task/context identity is retained, structured request and response values round-trip semantically, no more than one seller request is in flight, and the interaction is visible in the existing AG-UI chat stream.
4. Verify seller-call `INPUT_REQUIRED` and human-approval `INPUT_REQUIRED` are distinguishable and resume to their respective graph paths.

**Pass condition:** all four checks pass using documented or package-exported APIs, with no custom middleware, REST endpoints, or guessed extension points. Record the exact package classes/functions and the tested message lifecycle below before proceeding.

**Fail condition:** if any guarantee cannot be met through package-supported APIs, stop here. Report the unmet guarantee and the package behavior that blocks it; request an architecture decision. Do not implement a best-effort approximation.

### Feasibility result

**Status:** PASS (2026-10-23)

**Tested package API:**
- LangGraph: `langgraph.types.interrupt`, `langgraph.types.Command(resume=...)`, `CompiledStateGraph.ainvoke`, `aget_state`, `MemorySaver` checkpointer.
- ADK: `google.adk.agents.LlmAgent`, `google.adk.tools.FunctionTool`, `google.adk.models.lite_llm.LiteLlm`, `ag_ui_adk.AGUIToolset`.
- A2A SDK: `a2a.client.ClientFactory`, `ClientConfig(streaming=True)`, `SendMessageRequest`, `commerce_core.cards.fetch_agent_card`.
- Buyer A2A: `buyer_agent.executor.BuyerExecutor`, `buyer_agent.server.create_app(..., mediated=True)`.
- Commerce helpers: `commerce_core.a2a_parts.make_message/part_value/first_envelope`, `commerce_core.extension.wrap_payload`.

**Test command:** `uv run pytest tests/integration/test_mediation_gate.py tests/integration/test_mediated_graph.py tests/unit/test_buyer_executor_mediated.py tests/unit/test_orchestrator_mediation.py -q` (plus full suite: 57 passed).

**Result:** All four Task 0 checks pass:
1. Package-supported composition proven (hybrid: RemoteA2aAgent reserved for agent-card discovery; FunctionTool over A2A SDK for transport).
2. Buyer A2A task -> `seller_call` pause -> one seller request through the orchestrator -> resume of the same buyer checkpoint with the seller result.
3. Assertions: original task/context identity retained; structured RFQ/offer values round-trip semantically (not byte identity); max observed seller-call concurrency = 1; interaction recorded in the buyer trace that feeds the AG-UI chat stream.
4. `seller_call` INPUT_REQUIRED and `order_approval` INPUT_REQUIRED are distinguishable via the `reason` field and resume to their respective graph paths.

**Constraints recorded:**
- Interrupt node restarts on resume; RFQ construction and budget guardrail are idempotent (no side effects before `interrupt()`).
- DataPart round-trip asserted semantically (protobuf-byte identity not claimed).
- CopilotKit middleware remains in its supported role; seriality is structural in the buyer graph (pause/resume), not middleware dispatch or prompt wording.
- Mediated mode currently covers the RFQ phase only; counters, accept, and order migration are Plan B (Tasks 1-4) scope.

## Task 1: Buyer graph contract — contingent on Task 0 passing

- Reuse the existing commerce contracts and A2A payload helpers; do not introduce generic duplicate request/result models where existing types already represent the operation.
- Replace direct seller calls and parallel seller fan-out with the package-native request/pause/resume path proven in Task 0.
- Use a real LangGraph `interrupt()` and resume with `Command(resume=...)` under the same checkpoint thread ID. Keep seller-call and approval interrupt reasons explicit and separately validated.
- Apply each seller result to graph state, then continue deterministically to the next seller or existing ranking step. Preserve buyer-side mandate checks, offer validation, and budget-redaction guardrails.
- Test the graph snapshot at the pause and after each resume, including checkpoint identity and the absence of direct seller-client calls.

## Task 2: Orchestrator mediation — contingent on Task 0 passing

- Implement only the exact ADK/A2A composition proven in Task 0. Use registered agent cards and the SDK's A2A client behavior for transport, authentication, and task continuation.
- Ensure sequencing is structural and observable; prompt instructions alone do not satisfy the one-in-flight-call requirement.
- Do not add seller REST helpers or extend `A2AMiddlewareAgent` through undocumented `tools`/`agentTools` properties. Keep the existing middleware in its supported role and configuration.
- Test one seller request at a time, seller errors/timeouts, result delivery to the original buyer task, and the resulting AG-UI events.

## Task 3: Approval and ordering regression coverage

- Keep buyer approval as its existing independent LangGraph interrupt/resume flow.
- Verify rejection places no order and approval resumes ordering only after the decision is recorded.
- Verify seller-call errors cannot be interpreted as approval, and approval payloads cannot be interpreted as seller results.

## Task 4: Remove the legacy path and verify

- Remove direct buyer-to-seller client usage only after mediated sourcing, counters, and post-approval order operations are covered by passing tests.
- Run the targeted buyer graph, executor, A2A protocol, and orchestration integration tests, then the full Python suite and console typecheck.
- Confirm the trace, negotiation ledger, and chat display remain coherent after removing the direct path.

## Acceptance tests

- Full RFQ and counteroffer flow through orchestrator mediation with maximum observed seller-call concurrency of one.
- Seller error/timeout is returned to the same buyer checkpoint and handled without losing or duplicating negotiation state.
- Structured request and response values survive the complete A2A round trip semantically.
- Chat contains the orchestrator-mediated seller request and response events.
- Human rejection creates no order; approval is required before any order call.
- No buyer graph execution can reach a direct seller A2A client after migration.

## Execution rule

Tasks 1–4 are gated on Task 0. If Task 0 fails, implementation is not authorized by this plan; revise the architecture with the user before continuing.
