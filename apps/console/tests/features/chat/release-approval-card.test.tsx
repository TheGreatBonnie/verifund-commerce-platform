import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReleaseApprovalCard } from "@/features/chat/verifund-tools";

const HASH = "a".repeat(64);

function args(projection: Record<string, unknown> | null) {
  return {
    run_id: "run-1",
    transaction_id: "vf_1",
    agreement_version: 1,
    agreement_hash: HASH,
    message: "Release this transaction.",
    projection,
  } as any;
}

const permitted = args({
  transaction_id: "vf_1",
  state: "RELEASE_PERMITTED",
  amount_cents: 123400,
  currency: "USD",
  evidence: {
    required: ["serial", "provenance"],
    received: ["serial"],
  },
  verification: {
    status: "RELEASE_PERMITTED",
    reasons: [],
    override_allowed: false,
  },
});

describe("ReleaseApprovalCard", () => {
  it("shows a verified pill, the release amount, and evidence progress", () => {
    render(<ReleaseApprovalCard args={permitted} onDecision={vi.fn()} />);

    expect(screen.getByText("Verified")).toHaveClass("mm-status-pill");
    expect(
      screen.getByText("Releasing $1,234.00 for transaction vf_1."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("1/2 required evidence items received"),
    ).toBeInTheDocument();
  });

  it("shows a review-required pill and verification reasons", () => {
    render(
      <ReleaseApprovalCard
        args={args({
          transaction_id: "vf_1",
          state: "REVIEW_REQUIRED",
          amount_cents: 5000,
          evidence: { required: ["serial"], received: ["serial"] },
          verification: {
            status: "REVIEW_REQUIRED",
            reasons: ["battery below threshold"],
            override_allowed: true,
          },
        })}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByText("Review required")).toHaveClass(
      "mm-status-pill",
      "is-amber",
    );
    expect(
      screen.getByText(
        "Verification: REVIEW_REQUIRED · battery below threshold",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/override the verification failure/i)).toBeInTheDocument();
  });

  it("keeps the decision blocked when the projection is missing", () => {
    render(
      <ReleaseApprovalCard args={args(null)} onDecision={vi.fn()} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      /waiting for the transaction projection/i,
    );
    expect(screen.getByRole("button", { name: /release funds/i })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("binds the heading to the card via aria-labelledby", () => {
    render(<ReleaseApprovalCard args={permitted} onDecision={vi.fn()} />);

    const card = screen.getByTestId("verifund-release");
    expect(card).toHaveAttribute("aria-labelledby", "verifund-release-title");
    expect(document.getElementById("verifund-release-title")).toHaveTextContent(
      "Release this transaction.",
    );
  });
});
