import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "@/features/chat/components/approval-card";

/**
 * The orchestrator copies the Buyer's award into the HITL tool arguments, so
 * the console can receive a partial award. The card must still render: a throw
 * inside the HITL render replaces the whole approval with a crashed conversation.
 */
describe("ApprovalCard with a partial award", () => {
  const winner = {
    seller_id: "aurora-supply",
    seller_name: "Aurora Supply",
    offer_id: "EX-MACBOOK-AIR-2",
    currency: "USD",
    total_cents: 111149,
    valid_until: new Date(Date.now() + 3_600_000).toISOString(),
  };

  it("renders when the echoed award omits mandate_checks", () => {
    render(
      <ApprovalCard
        award={
          {
            winner,
            score: 88.07,
            alternatives: [],
            scores: {},
          } as never
        }
        mandate={{} as never}
        message="Approve the award to Aurora Supply for $1,111.49?"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.getByRole("heading", { name: /approve this order/i })).toBeTruthy();
    expect(screen.getByText("Aurora Supply")).toBeTruthy();
  });

  it("does not claim the mandate checks passed when they were not provided", () => {
    render(
      <ApprovalCard
        award={
          {
            winner,
            score: 88.07,
            alternatives: [],
            scores: {},
          } as never
        }
        mandate={{} as never}
        message="Approve the award to Aurora Supply for $1,111.49?"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.queryByText(/all deterministic mandate checks passed/i)).toBeNull();
    expect(screen.getByText(/mandate check details were not included/i)).toBeTruthy();
  });
});
