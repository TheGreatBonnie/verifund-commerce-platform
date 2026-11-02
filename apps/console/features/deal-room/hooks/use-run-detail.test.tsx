import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  agent: {
    threadId: "",
    messages: [] as Array<{ role?: string; content?: unknown }>,
    addMessage: vi.fn(),
    setMessages: vi.fn(),
    setState: vi.fn(),
  },
  isReady: true,
  connectAgent: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  UseAgentUpdate: {
    OnMessagesChanged: "messages",
    OnStateChanged: "state",
    OnRunStatusChanged: "run-status",
  },
  useAgent: () => ({ agent: mocks.agent, isReady: mocks.isReady }),
  useCopilotKit: () => ({
    copilotkit: {
      connectAgent: mocks.connectAgent,
      runAgent: mocks.runAgent,
    },
  }),
}));

vi.mock("@/features/sellers/use-registry", () => ({
  useRegistry: () => ({
    sellers: [],
    isLoading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock("@/features/deal-room/hooks/use-run-trace", () => ({
  useRunTrace: () => ({ data: [], error: null }),
}));

vi.mock("@/lib/api", () => ({
  fetchRun: vi.fn(() => new Promise(() => {})),
}));

import { useRunDetail } from "./use-run-detail";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useRunDetail pending brief", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    mocks.isReady = true;
    mocks.agent.threadId = "";
    mocks.agent.messages = [];
    mocks.agent.addMessage.mockReset();
    mocks.connectAgent.mockReset();
    mocks.runAgent.mockReset();
    mocks.runAgent.mockResolvedValue(undefined);
  });

  it("starts the pending brief once even when the hook re-renders while connecting", async () => {
    let finishConnect!: () => void;
    mocks.connectAgent.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishConnect = resolve;
        }),
    );
    const brief = "Find and negotiate a 27-inch 4K monitor.";
    window.sessionStorage.setItem("marketmesh:pendingBrief", brief);

    const { rerender } = renderHook(() => useRunDetail("thread-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(mocks.connectAgent).toHaveBeenCalledTimes(1));

    // Re-render under the same conditions that used to tear the effect down
    // while the connection was still in flight.
    mocks.isReady = false;
    rerender();
    mocks.isReady = true;
    rerender();

    // The handoff must survive until the run is actually dispatched.
    expect(window.sessionStorage.getItem("marketmesh:pendingBrief")).toBe(brief);

    await act(async () => {
      finishConnect();
    });

    await waitFor(() => expect(mocks.runAgent).toHaveBeenCalledTimes(1));
    expect(mocks.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(mocks.agent.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({ role: "user", content: brief }),
    );
    expect(window.sessionStorage.getItem("marketmesh:pendingBrief")).toBeNull();
  });

  it("dispatches the pending brief once under StrictMode", async () => {
    const resolvers: Array<() => void> = [];
    mocks.connectAgent.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolvers.push(resolve);
        }),
    );
    const brief = "Find and negotiate a 27-inch 4K monitor.";
    window.sessionStorage.setItem("marketmesh:pendingBrief", brief);

    renderHook(() => useRunDetail("thread-strict"), {
      wrapper: createWrapper(),
      reactStrictMode: true,
    });

    // StrictMode re-runs mount effects while the connection is still in
    // flight; the one-shot guard must survive so the same brief does not
    // dispatch a second, locked run.
    await waitFor(() => expect(mocks.connectAgent).toHaveBeenCalledTimes(1));

    await act(async () => {
      for (const resolve of resolvers) resolve();
    });

    await waitFor(() => expect(mocks.runAgent).toHaveBeenCalledTimes(1));
    expect(mocks.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem("marketmesh:pendingBrief")).toBeNull();
  });
});
