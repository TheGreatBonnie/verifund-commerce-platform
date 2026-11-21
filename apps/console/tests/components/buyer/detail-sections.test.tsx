import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SettlementRail } from "@/components/buyer/fulfillment/settlement-rail";
import { VerificationPanel } from "@/components/buyer/fulfillment/verification-panel";
import { DisputesPanel } from "@/components/buyer/fulfillment/disputes-panel";
import { StructuredDataPanel } from "@/components/buyer/shared/structured-data-panel";

describe("SettlementRail", () => {
  it("renders only factual events plus a derived next step — never fabricated milestones", () => {
    render(
      <SettlementRail
        events={[
          { type: "agreement_created", status: "complete", at: "2026-01-01T00:00:00Z", seq: 1 },
          { type: "payment_authorized", status: "complete", at: "2026-01-02T00:00:00Z", seq: 2 },
        ]}
        nextAction="awaiting_evidence"
      />,
    );

    expect(screen.getByText("Agreement Created")).toBeInTheDocument();
    expect(screen.getByText("Payment Authorized")).toBeInTheDocument();
    expect(screen.getByText(/next: awaiting evidence/i)).toBeInTheDocument();
    expect(screen.queryByText(/payout/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("shows an honest empty state when there are no events and no next action", () => {
    render(<SettlementRail events={[]} />);
    expect(screen.getByText(/no settlement activity yet/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});

describe("VerificationPanel", () => {
  it("surfaces verification status and every reason", () => {
    render(
      <VerificationPanel
        verification={{
          status: "failed",
          reasons: ["Evidence expired", "Seller mismatch"],
          checked_at: "2026-01-03T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: /verification/i })).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Evidence expired")).toBeInTheDocument();
    expect(screen.getByText("Seller mismatch")).toBeInTheDocument();
  });

  it("explains when verification has not run", () => {
    render(<VerificationPanel verification={null} />);
    expect(screen.getByText(/no verification results yet/i)).toBeInTheDocument();
  });
});

describe("DisputesPanel", () => {
  it("lists dispute records with claim, reason and status", () => {
    render(
      <DisputesPanel
        disputes={[
          {
            dispute_id: "d1",
            claim_type: "inspection",
            reason_code: "buyer_dispute",
            claim: "Item not as described",
            status: "open",
          },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: /disputes/i })).toBeInTheDocument();
    expect(screen.getByText("Item not as described")).toBeInTheDocument();
    expect(screen.getByText("Buyer Dispute")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("renders nothing when there are no disputes", () => {
    const { container } = render(<DisputesPanel disputes={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("StructuredDataPanel", () => {
  it("shows labelled scalar fields first and keeps raw JSON in a disclosure", () => {
    render(
      <StructuredDataPanel
        title="Payment"
        data={{ id: "pay_1", amount_cents: 5000, status: "captured" }}
        rawLabel="View raw payment"
      />,
    );
    expect(screen.getByRole("heading", { name: "Payment" })).toBeInTheDocument();
    expect(screen.getByText("Amount Cents")).toBeInTheDocument();
    expect(screen.getByText("5000")).toBeInTheDocument();
    expect(screen.getByText("View raw payment")).toBeInTheDocument();
  });
});
