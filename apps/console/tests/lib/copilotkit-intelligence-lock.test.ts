import { describe, expect, it, vi } from "vitest";
import { EventType, type RunAgentInput } from "@ag-ui/client";
import { of } from "rxjs";
// Internal entry point: the Intelligence run handler is not re-exported from
// `@copilotkit/runtime/v2`. This test characterises the lock behavior our
// CopilotKit route depends on, so it intentionally exercises that handler.
// @ts-expect-error -- the internal handler is published without type declarations
import { handleIntelligenceRun } from "../../node_modules/@copilotkit/runtime/dist/v2/runtime/handlers/intelligence/run.mjs";

const THREAD_ID = "thread-lock-release-test";
const RUN_ID = "run-lock-release-test";

/**
 * CopilotKit core starts a new run on the same thread when a HITL tool's
 * `respond()` resolves. That follow-up must not be rejected with 409 while the
 * preceding run's lock is still held, so a normal stream completion has to
 * release the lock.
 */
describe("Intelligence run thread-lock release", () => {
  it("releases the thread lock once the runner stream completes", async () => {
    const cleanupThreadLock = vi.fn(async () => ({}));
    const acquireThreadLock = vi.fn(async () => ({
      threadId: THREAD_ID,
      runId: RUN_ID,
      joinToken: "join-token",
      ttlSeconds: 20,
    }));

    const runtime = {
      intelligence: {
        ɵacquireThreadLock: acquireThreadLock,
        ɵcleanupThreadLock: cleanupThreadLock,
        ɵrenewThreadLock: vi.fn(async () => ({})),
        ɵgetClientWsUrl: vi.fn(() => "wss://example.invalid/client"),
        // 1.79.0 used getThreadMessages; 1.85.0 uses this ID-only lookup.
        getThreadMessages: vi.fn(async () => ({ messages: [] })),
        ɵgetThreadMessageIds: vi.fn(async () => []),
        getOrCreateThread: vi.fn(async () => ({
          thread: { id: THREAD_ID, agentId: "test-agent", name: "Test thread" },
          created: false,
        })),
      },
      identifyUser: vi.fn(async () => ({ id: "user-1", name: "Test User" })),
      generateThreadNames: false,
      telemetry: { capture: vi.fn() },
      lockTtlSeconds: 20,
      lockHeartbeatIntervalSeconds: 15,
      runner: {
        run: vi.fn(() =>
          of(
            { type: EventType.RUN_STARTED, threadId: THREAD_ID, runId: RUN_ID },
            { type: EventType.RUN_FINISHED, threadId: THREAD_ID, runId: RUN_ID },
          ),
        ),
      },
    };

    const input: RunAgentInput = {
      threadId: THREAD_ID,
      runId: RUN_ID,
      tools: [],
      context: [],
      messages: [{ id: "m1", role: "user", content: "hello" }],
      state: {},
      forwardedProps: {},
    };

    const response = await handleIntelligenceRun({
      // The handler is untyped at this internal path; the shape matches the
      // runtime object our CopilotRuntime constructs in the API route.
      runtime: runtime as never,
      request: new Request("http://localhost/api/copilotkit/agent/test/run"),
      agentId: "test-agent",
      agent: { abortRun: vi.fn() } as never,
      input,
    });

    expect(response.status).toBe(200);

    // On stream completion the runtime must issue the compare-and-delete that
    // frees the thread for the HITL follow-up run.
    expect(cleanupThreadLock).toHaveBeenCalledWith({
      threadId: THREAD_ID,
      runId: RUN_ID,
    });
  });
});
