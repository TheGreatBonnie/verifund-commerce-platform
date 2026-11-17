import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  addMessage: vi.fn(),
  runAgent: vi.fn(),
  agent: { isRunning: false },
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: { ...hooks.agent, addMessage: hooks.addMessage } }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { EvidenceWaitCard } from "@/features/chat/components/evidence-wait-card";

describe("EvidenceWaitCard", () => {
  beforeEach(() => {
    hooks.addMessage.mockClear();
    hooks.runAgent.mockClear();
    hooks.agent.isRunning = false;
    vi.useRealTimers();
  });

  it("never starts a run on its own", () => {
    vi.useFakeTimers();
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    expect(screen.getByTestId("verifund-evidence-wait").textContent).toContain(
      "Waiting for seller evidence",
    );

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(hooks.addMessage).not.toHaveBeenCalled();
    expect(hooks.runAgent).not.toHaveBeenCalled();
  });

  it("checks status once when the user asks", () => {
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    fireEvent.click(screen.getByRole("button", { name: /check status/i }));

    expect(hooks.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "user",
        content: "Check Verifund status",
      }),
    );
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
  });

  it("does not start a check while the agent is running", () => {
    hooks.agent.isRunning = true;
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    const button = screen.getByRole("button", { name: /check status/i });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.click(button);

    expect(hooks.addMessage).not.toHaveBeenCalled();
    expect(hooks.runAgent).not.toHaveBeenCalled();
  });
});
