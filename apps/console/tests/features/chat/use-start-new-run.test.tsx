import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  agentId: undefined as string | undefined,
  startNewThread: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useThreads: ({ agentId }: { agentId: string }) => {
    hooks.agentId = agentId;
    return { startNewThread: hooks.startNewThread };
  },
}));

import { useStartNewRun } from "@/features/chat/use-start-new-run";

describe("useStartNewRun", () => {
  beforeEach(() => {
    hooks.startNewThread.mockClear();
    hooks.agentId = undefined;
  });

  it("mints a fresh thread scoped to the orchestrator agent", () => {
    const { result } = renderHook(() => useStartNewRun());

    result.current.startNewRun();

    expect(hooks.agentId).toBe("marketmesh_orchestrator");
    expect(hooks.startNewThread).toHaveBeenCalledTimes(1);
  });
});
