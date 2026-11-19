import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const cpk = vi.hoisted(() => ({
  onError: undefined as
    | ((event: { code?: string; error?: Error }) => void)
    | undefined,
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children, onError }: any) => {
    cpk.onError = onError;
    return <div data-testid="copilot-provider">{children}</div>;
  },
  CopilotChatConfigurationProvider: ({ children }: any) => <div>{children}</div>,
  useAgent: () => ({
    agent: { agentId: "marketmesh_orchestrator", isRunning: false },
  }),
  useCopilotKit: () => ({ copilotkit: { runAgent: cpk.runAgent } }),
}));

import { CopilotProvider } from "@/providers/copilot-provider";

describe("CopilotProvider", () => {
  beforeEach(() => {
    cpk.onError = undefined;
    cpk.runAgent.mockClear();
  });

  it("shows a busy notice when the thread lock error fires", () => {
    render(
      <CopilotProvider>
        <div>console</div>
      </CopilotProvider>,
    );
    expect(screen.queryByRole("alert")).toBeNull();

    act(() => {
      cpk.onError?.({
        code: "agent_thread_locked",
        error: new Error("Thread is locked"),
      });
    });

    expect(screen.getByRole("alert").textContent).toMatch(/busy/i);
    expect(screen.getByText("console")).toBeInTheDocument();
  });

  it("does not show the notice for other copilot errors", () => {
    render(
      <CopilotProvider>
        <div>console</div>
      </CopilotProvider>,
    );

    act(() => {
      cpk.onError?.({
        code: "agent_run_failed",
        error: new Error("unrelated failure"),
      });
    });

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
