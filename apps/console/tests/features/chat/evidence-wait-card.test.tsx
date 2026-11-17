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
    render(
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
