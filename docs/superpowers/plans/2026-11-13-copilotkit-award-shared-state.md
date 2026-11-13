# CopilotKit Award Shared State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-authored award transport through CopilotKit chat tool arguments with CopilotKit full shared state, eliminating the `BuyerAgreementRequest` Pydantic `list_type` validation errors caused by `{"item": ...}` array mangling.

**Architecture:** The orchestrator agent writes the award into CopilotKit full shared state via AG-UI state tools (`AGUISendStateSnapshot`/`AGUISendStateDelta`); the frontend reads it via `useAgent()` → `agent.state`; Verifund HITL tools take IDs/status only and read payload from shared state.

**Tech Stack:** CopilotKit 1.79.0 (`@copilotkit/react-core@1.79.0`, `@copilotkit/runtime@1.79.0`), React + Zod (console frontend), Google ADK orchestrator (`apps/orchestrator_agent`), Pydantic buyer agent (`apps/buyer_agent`).

**Spec:** `docs/superpowers/specs/2026-11-13-copilotkit-award-shared-state-design.md`

## Global Constraints

- CopilotKit version floor: `@copilotkit/react-core@1.79.0` / `@copilotkit/runtime@1.79.0`.
- No fallback to the legacy task-payload award path; fail hard.
- HITL tools must not receive `award`/`agreement`/`projection` payload args; read from shared state.
- Award lives in shared state as a single nested `award` object.

---

## Task 1: Update console HITL Zod schemas to drop award-shaped args

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx` (`agreementSchema`, `fundingApprovalArgsSchema`, `releaseApprovalArgsSchema`, `paypalCheckoutArgsSchema`, `agreementApprovalArgsSchema`)

**Interfaces:**
- Consumes: shared-state design (`agent.state.award`).
- Produces: HITL arg schemas that accept task/status/IDs only.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/console/tests/features/chat/verifund-tools.test.tsx
// Existing tests pass award-shaped args and must now expect schemas without them.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter console test verifund-tools`
Expected: FAIL (schemas still require award fields).

- [ ] **Step 3: Write minimal implementation**

Remove award/agreement/projection requirements from Zod schemas in `apps/console/features/chat/verifund-tools.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter console test verifund-tools`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/verifund-tools.tsx apps/console/tests/features/chat/verifund-tools.test.tsx
git commit -m "fix(console): drop award-shaped args from Verifund HITL schemas"
```

## Task 2: Wire frontend shared-state reads for agreement approval HITL

**Files:**
- Modify: `apps/console/features/chat/chat.tsx` (HITL `useHumanInTheLoop` render for `request_verifund_agreement_approval`)
- Modify: `apps/console/features/chat/verifund-tools.tsx` (cards consume state)

**Interfaces:**
- Consumes: `agent.state.award` via `useAgent()`.
- Produces: approval/funding cards that read award from shared state.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/console/tests/features/chat/agreement-approval-hitl.test.tsx
// Expect cards to read award from agent state, not args.
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Use `const { agent } = useAgent()` and read `agent.state.award`; pass to `ApprovalCard`.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/chat.tsx apps/console/features/chat/verifund-tools.tsx apps/console/tests/features/chat/agreement-approval-hitl.test.tsx
git commit -m "feat(console): render agreement HITL from shared state"
```

## Task 3: Wire remaining HITL surfaces (funding, checkout, release) to shared state

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`, `apps/console/features/chat/verifund-tools.tsx`, `apps/console/app/(console)/agreements/[id]/actions.ts` (if needed)

**Interfaces:**
- Consumes: `agent.state` for funding/checkout/release payloads.
- Produces: all four Verifund HITL tools fully state-driven.

- [ ] **Step 1: Write the failing tests**

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Write minimal implementation**

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

## Task 4: Update orchestrator ADK tools to drop award payload args

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` (tools `verifund_create_agreement`, `verifund_fund`, `verifund_checkout`, `verifund_release`, `request_verifund_*` HITL wrappers)

**Interfaces:**
- Consumes: CopilotKit runtime state access for custom ADK agent.
- Produces: tools that read award/agreement/projection from shared state.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_orchestrator_verifund.py`

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Write minimal implementation**

Remove `award` param from `verifund_create_agreement`; read from state.

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

## Task 5: Verify CopilotKit runtime state wiring for custom ADK agent and adjust backend

**Files:**
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts` (runtime/state wiring, if needed)

**Interfaces:**
- Consumes: CopilotKit runtime state tools for custom ADK agents.
- Produces: working agent→UI state writes for the custom orchestrator.

- [ ] **Step 1: Write failing checks/tests**

- [ ] **Step 2: Run test to verify failing**

- [ ] **Step 3: Write minimal implementation**

- [ ] **Step 4: Run test to verify passing**

- [ ] **Step 5: Commit**

---

## Self-Review Checklist

- [ ] No placeholders remain in the plan.
- [ ] Task interfaces are consistent (signatures produced by one task consumed by the next).
- [ ] Spec coverage: design decisions (transport, shape, writer, scope, fallback, custom ADK) each map to a task.
