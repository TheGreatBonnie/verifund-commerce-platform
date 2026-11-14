import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({ fetchRun: vi.fn() }));

vi.mock("@/lib/api", () => ({ fetchRun: api.fetchRun }));

import { AwardApproval } from "@/features/chat/components/award-approval";

const award = {
  winner: {
    seller_id: "aurora-supply",
    seller_name: "Aurora Supply",
    offer_id: "EX-MACBOOK-AIR-2",
    currency: "USD",
    total_cents: 111149,
    valid_until: new Date(Date.now() + 3_600_000).toISOString(),
  },
  score: 88.07,
  alternatives: [],
  scores: {},
  mandate_checks: ["Price within ceiling"],
};

/**
 * The orchestrator only forwards the Buyer's task id. The console must load the
 * award itself, so the HITL tool never depends on the model copying a 10KB
 * award into its tool arguments.
 */
describe("AwardApproval", () => {
  beforeEach(() => {
    api.fetchRun.mockReset();
  });

  it("loads the award from the run when no award argument is passed", async () => {
    api.fetchRun.mockResolvedValue({ run_id: "run-1", award });

    render(
      <AwardApproval
        taskId="run-1"
        message="Approve the award to Aurora Supply for $1,111.49?"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(await screen.findByText("Aurora Supply")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /approve this order/i })).toBeTruthy();
    expect(api.fetchRun).toHaveBeenCalledWith("run-1");
  });

  it("uses the award argument without fetching when it is already complete", () => {
    render(
      <AwardApproval
        taskId="run-1"
        award={award as never}
        message="Approve?"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.getByText("Aurora Supply")).toBeTruthy();
    expect(api.fetchRun).not.toHaveBeenCalled();
  });

  it("reports a load failure instead of rendering nothing", async () => {
    api.fetchRun.mockRejectedValue(new Error("500"));

    render(
      <AwardApproval
        taskId="run-1"
        message="Approve?"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText(/could not load the award/i)).toBeTruthy();
  });
});
