# Verifund Evidence HITL Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Verifund chat wait visibly at `evidence_pending` and resume the verifund agent graph via the existing status A2A skill once seller evidence is verified, then surface the release-approval HITL.

**Architecture:** The verifund graph's `await_evidence` interrupt already exists; the orchestrator's `verifund_status` tool already dispatches `verifund.transaction.status`, whose `_transaction_status` resumes the graph with `Command(resume={"projection": ...})` when the projection is ready. This plan adds (1) orchestrator instructions that treat `evidence_pending` as a wait state, and (2) a console card that polls `verifund_status` via CopilotKit v2 programmatic control. No control-plane or verifund-agent changes.

**Tech Stack:** Python 3 / pytest (orchestrator), Next.js / React 19 / Vitest / `@copilotkit/react-core/v2` (console).

**Spec:** `docs/superpowers/specs/2026-11-17-verifund-evidence-hitl-resume-design.md`

## Global Constraints

- No new environment variables, A2A clients, or control-plane changes.
- No changes to `apps/verifund_agent/verifund_agent/graph.py` or its checkpointer.
- Never block inside an orchestrator tool at `EVIDENCE_PENDING` (unbounded latency, serverless timeouts).
- Preserve exact `task_id` / `context_id` / `run_id` from tool results; never invent HITL arguments.
- Before writing ANY code under `apps/console`, read `apps/console/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md` (per `apps/console/AGENTS.md`); also check `apps/console/node_modules/next/dist/docs/01-app/02-guides/server-and-client-boundary.md` if the client boundary is unclear.
- TDD: watch each test fail before writing the implementation; commit after each task.
- After code changes, run `graphify update .`.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/orchestrator_agent/orchestrator_agent/agent.py` | Orchestrator prompt rule for `evidence_pending` → status refresh → release; tool docstring |
| `tests/unit/test_orchestrator_verifund.py` | Assert the prompt rule |
| `apps/console/features/chat/components/evidence-wait-card.tsx` | New client component: waiting UI + interval that appends a status-check message and runs the agent |
| `apps/console/tests/features/chat/evidence-wait-card.test.tsx` | New test: waiting state, polling starts/stops |
| `apps/console/features/chat/chat.tsx` | Render `EvidenceWaitCard` for `evidence_pending` in `verifund_status` / `verifund_evidence_review` renderers |
| `apps/console/tests/features/chat/chat.test.tsx` | Assert renderer shows waiting card at `evidence_pending` |

---

### Task 1: Orchestrator instruction treats evidence as a wait state

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py:269-275` (instruction) and `:629` (docstring)
- Test: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Consumes: `MARKETMESH_ORCHESTRATOR_INSTRUCTION` (module constant in `agent.py`).
- Produces: prompt text directing the LLM to call `verifund_status` at `evidence_pending` and then the existing `request_verifund_release_approval` HITL; no new tool.

- [ ] **Step 1: Add the failing test**

Add to `tests/unit/test_orchestrator_verifund.py` (beside `test_the_checkout_tool_and_instruction_are_registered`):

```python
def test_instruction_waits_for_evidence_then_surfaces_release() -> None:
    from orchestrator_agent.agent import MARKETMESH_ORCHESTRATOR_INSTRUCTION

    assert "checkpoint evidence_pending" in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    assert (
        "verifund_status with the exact task_id, context_id, and run_id"
        in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    )
    assert (
        "request_verifund_release_approval"
        in MARKETMESH_ORCHESTRATOR_INSTRUCTION
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_orchestrator_verifund.py::test_instruction_waits_for_evidence_then_surfaces_release -q`
Expected: FAIL on the first missing string (feature absent).

- [ ] **Step 3: Update the instruction and docstring**

In `agent.py`, replace the existing "After funding..." bullet:

```python
- After funding, call verifund_evidence_review with the same
  task_id, context_id, run_id, and seller_card_url. It places
  the purchase order with the Seller and polls funding and
  evidence. Do not call the Seller or place the purchase order
  yourself.
```

with (preserve the two-space continuation indentation used throughout the instruction):

```python
- After funding, call verifund_evidence_review with the same
  task_id, context_id, run_id, and seller_card_url. It places
  the purchase order with the Seller, then returns a working
  result at checkpoint evidence_pending. Do not call the Seller
  or place the purchase order yourself.
- When a tool result has checkpoint evidence_pending, treat it as
  a wait state, not success: the Seller is still submitting
  fulfillment evidence. On the next status refresh, call
  verifund_status with the exact task_id, context_id, and run_id;
  its status check resumes the verifund agent when the evidence
  projection is ready. Never invent a verified or released state.
```

Change the `verifund_evidence_review` docstring from:

```python
        """Place the purchase order and poll funding, evidence, or release."""
```

to:

```python
        """Place the purchase order; evidence and release resume on status refresh."""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_orchestrator_verifund.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py tests/unit/test_orchestrator_verifund.py
git commit -m "feat(verifund): instruct orchestrator to wait at evidence_pending"
```

---

### Task 2: Console EvidenceWaitCard component

**Files:**
- Read first: `apps/console/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`
- Create: `apps/console/features/chat/components/evidence-wait-card.tsx`
- Test: `apps/console/tests/features/chat/evidence-wait-card.test.tsx`

**Interfaces:**
- Consumes: `useAgent({ agentId: "marketmesh_orchestrator" })` → `{ agent }` with `agent.isRunning`, `agent.addMessage`; `useCopilotKit()` → `{ copilotkit }` with `copilotkit.runAgent`. Both from `@copilotkit/react-core/v2` (canonical pattern: https://docs.copilotkit.ai/programmatic-control).
- Produces: `EvidenceWaitCard({ checkpoint, pollIntervalMs? })` — renders waiting UI when `checkpoint === "evidence_pending"` and drives status refreshes.

- [ ] **Step 1: Read the Next.js client-component guide**

Run: `sed -n '1,160p' apps/console/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`
Confirm the `"use client"` directive is required for a component using `useEffect` and CopilotKit hooks.

- [ ] **Step 2: Write the failing test**

Create `apps/console/tests/features/chat/evidence-wait-card.test.tsx`:

```tsx
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  addMessage: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({
    agent: { isRunning: false, addMessage: hooks.addMessage },
  }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { EvidenceWaitCard } from "@/features/chat/components/evidence-wait-card";

describe("EvidenceWaitCard", () => {
  beforeEach(() => {
    hooks.addMessage.mockClear();
    hooks.runAgent.mockClear();
    vi.useRealTimers();
  });

  it("shows a waiting state and refreshes status while evidence is pending", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <EvidenceWaitCard checkpoint="evidence_pending" pollIntervalMs={1000} />,
    );

    expect(screen.getByTestId("verifund-evidence-wait").textContent).toContain(
      "Waiting for seller evidence",
    );

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(hooks.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "user",
        content: "Check Verifund status",
      }),
    );
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
  });

  it("stops refreshing when the checkpoint leaves evidence_pending", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <EvidenceWaitCard checkpoint="evidence_pending" pollIntervalMs={1000} />,
    );
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);

    rerender(
      <EvidenceWaitCard
        checkpoint="release_approval_required"
        pollIntervalMs={1000}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd apps/console && pnpm test tests/features/chat/evidence-wait-card.test.tsx`
Expected: FAIL — cannot resolve `@/features/chat/components/evidence-wait-card` (module missing).

- [ ] **Step 4: Implement the component**

Create `apps/console/features/chat/components/evidence-wait-card.tsx`:

```tsx
"use client";

import { useEffect } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";

export function EvidenceWaitCard({
  checkpoint,
  pollIntervalMs = 10_000,
}: {
  checkpoint?: string | null;
  pollIntervalMs?: number;
}) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { copilotkit } = useCopilotKit();

  useEffect(() => {
    if (checkpoint !== "evidence_pending" || pollIntervalMs <= 0) return;
    const timer = window.setInterval(() => {
      if (agent.isRunning) return;
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: "Check Verifund status",
      });
      void copilotkit.runAgent({ agent });
    }, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [agent, checkpoint, copilotkit, pollIntervalMs]);

  return (
    <div
      className="mm-chat-approval"
      role="status"
      data-testid="verifund-evidence-wait"
    >
      <p className="mm-kicker">Waiting for seller evidence</p>
      <p>
        The seller is submitting fulfillment evidence. This chat will continue
        automatically when the evidence is verified.
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/console && pnpm test tests/features/chat/evidence-wait-card.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/console/features/chat/components/evidence-wait-card.tsx apps/console/tests/features/chat/evidence-wait-card.test.tsx
git commit -m "feat(console): add evidence wait card that polls verifund status"
```

---

### Task 3: Wire the card into the chat renderers

**Files:**
- Modify: `apps/console/features/chat/chat.tsx:17-26` (imports), `:663-688` (`verifund_evidence_review` renderer), `:638-661` (`verifund_status` renderer)
- Test: `apps/console/tests/features/chat/chat.test.tsx`

**Interfaces:**
- Consumes: `EvidenceWaitCard` from Task 2; `parseVerifundToolResult` (already imported in `chat.tsx`) returns the tool result object as-is when it is an object.
- Produces: renderers show the waiting card instead of a success card when `parsed.checkpoint === "evidence_pending"`.

- [ ] **Step 1: Add the failing test**

Append to `apps/console/tests/features/chat/chat.test.tsx`:

```tsx
describe("chat evidence wait", () => {
  beforeEach(() => {
    hooks.useRenderTool.mockClear();
    hooks.addMessage.mockClear();
    hooks.runAgent.mockClear();
  });

  it("renders the waiting card for an evidence_pending tool result", () => {
    renderChat();
    const renderer = hooks.useRenderTool.mock.calls.find(
      ([tool]) => tool.name === "verifund_evidence_review",
    )?.[0].render;

    expect(renderer).toBeTruthy();
    render(
      renderer!({
        parameters: { run_id: "run-1" },
        status: "complete",
        result: {
          status: "working",
          checkpoint: "evidence_pending",
          data: { run_id: "run-1" },
        },
      }),
    );

    expect(screen.getByTestId("verifund-evidence-wait")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/console && pnpm test tests/features/chat/chat.test.tsx`
Expected: FAIL — `getByTestId("verifund-evidence-wait")` not found (renderer still shows `EvidenceSummaryCard`).

- [ ] **Step 3: Import and render the card**

In `apps/console/features/chat/chat.tsx`, add to the component import block near line 17:

```tsx
import { EvidenceWaitCard } from "@/features/chat/components/evidence-wait-card";
```

In the `verifund_evidence_review` render callback, immediately after the `response` variable and before the `return (`:

```tsx
      if (parsed.checkpoint === "evidence_pending") {
        return (
          <VerifundA2AExchange status={status} task={task} response={response}>
            <EvidenceWaitCard checkpoint={parsed.checkpoint} />
          </VerifundA2AExchange>
        );
      }
```

Apply the identical guard in the `verifund_status` render callback (same `parsed.checkpoint === "evidence_pending"` shape, placed after its `response` variable).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/console && pnpm test tests/features/chat/evidence-wait-card.test.tsx tests/features/chat/chat.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/chat.tsx apps/console/tests/features/chat/chat.test.tsx
git commit -m "feat(console): show evidence wait state in verifund chat cards"
```

---

### Task 4: Verification and graph refresh

**Files:** none (verification only).

- [ ] **Step 1: Run targeted Python tests**

Run: `.venv/bin/python -m pytest tests/unit/test_orchestrator_verifund.py tests/unit/test_seller_settlement_validation.py -q`
Expected: PASS.

- [ ] **Step 2: Run the console test suite**

Run: `cd apps/console && pnpm test`
Expected: PASS. If unrelated pre-existing failures appear, record them; do not fix unrelated code here.

- [ ] **Step 3: Refresh the code graph**

Run: `graphify update .`
Expected: graph rebuild completes.

- [ ] **Step 4: Update the spec status**

Edit `docs/superpowers/specs/2026-11-17-verifund-evidence-hitl-resume-design.md` line 3 from `**Status:** Proposed (awaiting review before implementation)` to `**Status:** Implemented`. Commit with `git commit -am "docs(verifund): mark evidence resume spec implemented"`.

---

## Self-Review (completed against the spec)

- **Spec coverage:** §4.2 → Task 1; §4.3 → Tasks 2-3; §4.4 data flow is realized by the existing status A2A skill (no new code); §3 evidence catalog is documentation only (no code task needed); §6 testing → Tasks 1-4.
- **No placeholders:** every task has concrete code and exact run commands.
- **Type consistency:** `EvidenceWaitCard({ checkpoint, pollIntervalMs })` is the only new interface; both renderers pass `checkpoint` as a string; `agent.addMessage` / `copilotkit.runAgent` match the CopilotKit v2 API and the existing test mocks.
- **Known constraint from existing mocks:** `chat.test.tsx` mocks `useAgent` without `isRunning`; `undefined` is falsy, so the guarded refresh still runs. The new component test mock includes `isRunning: false` explicitly.
