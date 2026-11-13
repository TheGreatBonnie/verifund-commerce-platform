# CopilotKit Award Shared State Design

> Design doc for the implementation plan: `docs/superpowers/plans/2026-11-13-copilotkit-award-shared-state.md`

## Problem

CopilotKit surfaced this error during an agent run:

```
[CopilotKit] Error (agent_run_error_event): Error: 3 validation errors for BuyerAgreementRequest
award.line_items
  Input should be a valid list [type=list_type, input_value={'item': {'sku': 'EX-ENTE...'Enterprise Ultrabook'}}, input_type=dict]
award.requirements
  Input should be a valid list ...
award.evidence_required
  Input should be a valid list ...
```

**Root cause:** the orchestrator agent (CopilotKit + custom Google ADK agent) carried the
award through LLM-authored tool arguments (`verifund_create_agreement(award=...)`).
The model re-serialized nested arrays, wrapping them as `{"item": …}`, which the buyer
agent's Pydantic `BuyerAgreementRequest` correctly rejects (`list_type` errors).

## Decision

Stop transporting the award via LLM tool arguments. Route it through **CopilotKit full
shared state** instead.

## Chosen approach (brainstorming → grilling outcomes)

1. **Transport:** full bidirectional shared state — agent writes, UI reads via `useAgent()`
   → `agent.state`; agent → UI via AG-UI state tools (`AGUISendStateSnapshot` /
   `AGUISendStateDelta`).
2. **State shape:** single nested `award` object (atomic snapshot).
3. **Writer:** agent writes the award via state tools when it reaches the award stage;
   frontend reads only.
4. **HITL scope:** all Verifund HITL surfaces — agent tools take IDs/status only and read
   payload from shared state; no `award`/`agreement`/`projection` args.
5. **Fallback:** none — fail hard; no legacy task-payload path.
6. **Custom ADK agent:** verify runtime state support later; design frontend for swappability.

## Constraints

- CopilotKit version in use: `@copilotkit/react-core@1.79.0` / `@copilotkit/runtime@1.79.0`
  (frontend hooks via `@copilotkit/react-core/v2`: `useAgent`, `useAgentContext`).
- Frontend Zod schemas (`agreementSchema`, `fundingApprovalArgsSchema`, etc.) must stop
  requiring award-shaped fields in tool args.
- Buyer agent keeps strict Pydantic validation (`AwardRequest.line_items`,
  `requirements`, `evidence_required` must be lists).

## Testing

- Update console HITL tests: `apps/console/tests/features/chat/agreement-approval-hitl.test.tsx`,
  `apps/console/tests/features/chat/verifund-tools.test.tsx`.
- Update orchestrator unit tests: `tests/unit/test_verifund_agent_graph.py`,
  `tests/unit/test_orchestrator_verifund.py`.
- Backend: verify CopilotKit runtime state wiring for the custom ADK agent.
