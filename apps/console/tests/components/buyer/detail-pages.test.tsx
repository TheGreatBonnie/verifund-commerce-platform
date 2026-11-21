import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getBuyerTransaction: vi.fn(),
  getBuyerFulfillment: vi.fn(),
  getBuyerInspection: vi.fn(),
}));
vi.mock("@/lib/buyer-transaction-api", () => api);

import { TransactionDetail } from "@/components/buyer/transactions/transaction-detail";
import { FulfillmentDetail } from "@/components/buyer/fulfillment/fulfillment-detail";

beforeEach(() => {
  api.getBuyerTransaction.mockReset();
  api.getBuyerFulfillment.mockReset();
  api.getBuyerInspection.mockReset();
  api.getBuyerInspection.mockResolvedValue(null);
});

describe("TransactionDetail", () => {
  it("shows a page-shaped busy skeleton while loading", () => {
    api.getBuyerTransaction.mockReturnValue(new Promise(() => {}));
    render(<TransactionDetail transactionId="tx_1" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("distinguishes a missing transaction from a failed load", async () => {
    const notFound: any = new Error("not found");
    notFound.status = 404;
    api.getBuyerTransaction.mockRejectedValue(notFound);
    render(<TransactionDetail transactionId="tx_1" />);
    expect(await screen.findByText(/does not exist/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /back to transactions/i }),
    ).toHaveAttribute("href", "/transactions");
  });

  it("leads with amount and state, structures raw data and renders a factual settlement rail", async () => {
    api.getBuyerTransaction.mockResolvedValue({
      transaction_id: "tx_1",
      status: "active",
      transaction_status: "FUNDED",
      payment_status: "PAID",
      seller_name: "Acme Supply",
      agreed_amount_cents: 12550,
      currency: "USD",
      agreement: {
        agreement_id: "agr_1",
        agreement_version: 2,
        status: "AGREED",
        currency: "USD",
        terms: {
          items: [{ name: "Acme Widget", quantity: 1 }],
          totals: { total_cents: 12550, currency: "USD" },
        },
      },
      payment: { payment_id: "pay_1", status: "captured" },
      timeline: [{ type: "agreement_created", status: "complete", at: "2026-01-01T00:00:00Z" }],
      fulfillment: {
        status: "in_progress",
        next_action: "submit_evidence",
        blockers: [{ code: "evidence_required", message: "Evidence is required." }],
      },
    });

    render(<TransactionDetail transactionId="tx_1" />);

    expect((await screen.findAllByText("USD 125.50"))[0]).toHaveClass(
      "mm-buyer-detail-amount",
    );
    expect(screen.getByText("Funded")).toHaveClass("mm-buyer-status-pill");
    expect(screen.getByText("Acme Widget")).toBeInTheDocument();
    expect(screen.getByTestId("buyer-agreement-card")).toBeInTheDocument();
    expect(screen.getByText("View raw agreement").closest("details")).toBeInTheDocument();
    expect(screen.getAllByText(/next: submit evidence/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/evidence is required/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /review in chat for tx_1/i }),
    ).toHaveAttribute("href", "/chat?transaction_id=tx_1&intent=review");
  });
});

describe("FulfillmentDetail", () => {
  it("renders verification, disputes and gated actions, with an enriched transaction reference", async () => {
    api.getBuyerFulfillment.mockResolvedValue({
      transaction_id: "tx_1",
      status: "in_progress",
      next_action: "awaiting_evidence",
      requirements: [],
      evidence: [],
      verification: { status: "failed", reasons: ["Evidence expired"] },
      disputes: [{ claim: "Not delivered", reason_code: "buyer_dispute", status: "open" }],
      shipment: { tracking_number: "TRK1", carrier: "DHL" },
      carrier_events: [{ status: "in_transit", occurred_at: "2026-01-04T00:00:00Z" }],
      blockers: [],
      allowed_actions: ["accept", "dispute"],
    });
    api.getBuyerTransaction.mockResolvedValue({
      transaction_id: "tx_1",
      agreed_amount_cents: 12550,
      currency: "USD",
      payment_status: "PAID",
      status: "active",
    });

    render(<FulfillmentDetail transactionId="tx_1" />);

    expect(await screen.findByText("Evidence expired")).toBeInTheDocument();
    expect(screen.getByText("Not delivered")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
    expect(screen.getByText("USD 125.50")).toBeInTheDocument();
    expect(screen.getByText("Paid")).toHaveClass("mm-buyer-status-pill");
    expect(screen.getAllByText(/in transit/i).length).toBeGreaterThan(0);
  });
});
