import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  agent: { agentId: "marketmesh_orchestrator", isRunning: false },
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: hooks.agent }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { useRunLaunch } from "@/features/chat/use-run-launch";

describe("useRunLaunch", () => {
  beforeEach(() => {
    hooks.runAgent.mockReset();
    hooks.runAgent.mockResolvedValue(undefined);
    hooks.agent.isRunning = false;
  });

  it("does not dispatch a second run while the agent is running", async () => {
    hooks.agent.isRunning = true;

    const { result } = renderHook(() => useRunLaunch());
    const dispatched = await result.current.runOnActiveThread();

    expect(dispatched).toBe(false);
    expect(hooks.runAgent).not.toHaveBeenCalled();
  });

  it("dispatches the run on the active thread when the agent is idle", async () => {
    const { result } = renderHook(() => useRunLaunch());
    const dispatched = await result.current.runOnActiveThread();

    expect(dispatched).toBe(true);
    expect(hooks.runAgent).toHaveBeenCalledWith({ agent: hooks.agent });
  });

  it("does not run the pre-dispatch action when the agent is busy", async () => {
    const prepare = vi.fn();
    hooks.agent.isRunning = true;

    const { result } = renderHook(() => useRunLaunch());
    await result.current.runOnActiveThread(prepare);

    expect(prepare).not.toHaveBeenCalled();
  });

  it("runs the pre-dispatch action before dispatching an idle run", async () => {
    const prepare = vi.fn();
    const { result } = renderHook(() => useRunLaunch());

    await result.current.runOnActiveThread(prepare);

    expect(prepare).toHaveBeenCalledTimes(1);
    expect(prepare.mock.invocationCallOrder[0]).toBeLessThan(
      hooks.runAgent.mock.invocationCallOrder[0],
    );
  });

  it("rejects a second dispatch while the first is still in flight", async () => {
    let release: (() => void) | undefined;
    hooks.runAgent.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useRunLaunch());

    const first = result.current.runOnActiveThread();
    const second = result.current.runOnActiveThread();

    await expect(second).resolves.toBe(false);
    release?.();
    await expect(first).resolves.toBe(true);
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
  });
});
