import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  agent: { agentId: "marketmesh_orchestrator", isRunning: false },
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: hooks.agent }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { ThreadLockNotice } from "@/features/chat/components/thread-lock-notice";

describe("ThreadLockNotice", () => {
  beforeEach(() => {
    hooks.runAgent.mockClear();
    hooks.agent.isRunning = false;
  });

  it("explains that the agent is busy and offers a retry", () => {
    render(<ThreadLockNotice onDismiss={vi.fn()} />);

    expect(screen.getByRole("alert").textContent).toMatch(/busy/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("dismisses the notice and retries the run", () => {
    const onDismiss = vi.fn();
    render(<ThreadLockNotice onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
  });

  it("does not retry while the agent is still running", () => {
    hooks.agent.isRunning = true;
    render(<ThreadLockNotice onDismiss={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(hooks.runAgent).not.toHaveBeenCalled();
  });
});
