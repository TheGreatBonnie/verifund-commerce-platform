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
    hooks.runAgent.mockReset();
    hooks.runAgent.mockResolvedValue(undefined);
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

  it("ignores a second status check while the first is still in flight", () => {
    let resolveRun: (() => void) | undefined;
    hooks.runAgent.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRun = resolve;
        }),
    );
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    const button = screen.getByRole("button", { name: /check status/i });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(hooks.addMessage).toHaveBeenCalledTimes(1);
    expect(hooks.runAgent).toHaveBeenCalledTimes(1);
    resolveRun?.();
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

  it("uses the waiting dossier shell with an amber pill and styled button", () => {
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    expect(screen.getByTestId("verifund-evidence-wait")).toHaveClass(
      "mm-approval",
      "is-waiting",
    );
    expect(screen.getByText("Evidence pending")).toHaveClass(
      "mm-status-pill",
      "is-amber",
    );
    expect(screen.getByRole("button", { name: /check status/i })).toHaveClass(
      "mm-button",
      "mm-button-signal",
    );
  });

  it("renders evidence progress when a projection is supplied", () => {
    render(
      <EvidenceWaitCard
        checkpoint="evidence_pending"
        projection={
          {
            evidence: {
              required: ["serial", "provenance"],
              received: ["serial"],
            },
          } as any
        }
      />,
    );

    expect(
      screen.getByText("1/2 required evidence items received"),
    ).toBeInTheDocument();
  });

  it("omits evidence progress when no projection is supplied", () => {
    render(<EvidenceWaitCard checkpoint="evidence_pending" />);

    expect(
      screen.queryByText(/required evidence items received/i),
    ).not.toBeInTheDocument();
  });
});
