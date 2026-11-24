import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BuyerAgreementCard } from "@/components/buyer/transactions/agreement-card";

const HASH = "a".repeat(64);

const agreement = {
  agreement_id: "agr_1",
  agreement_version: 1,
  transaction_id: "vf_1",
  currency: "USD",
  amount_cents: 123400,
  quantity: 12,
  status: "PENDING_BUYER",
  expires_at: "2026-11-05T12:00:00Z",
  created_at: "2026-11-04T12:00:00Z",
  agreement_hash: HASH,
  line_items: [
    {
      sku: "NC-700",
      name: "Nimbus NC-700 ANC Headset",
      quantity: 12,
      unit_price_cents: 10000,
      attributes: {
        image_url: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
        condition: "new",
        specs: "Adaptive audio · 30-hour battery",
      },
    },
  ],
  terms: {
    parties: { seller: { display_name: "NovaTech" } },
    items: [
      {
        sku: "NC-700",
        name: "Nimbus NC-700 ANC Headset",
        quantity: 12,
        unit_price_cents: 10000,
        attributes: { condition: "new" },
      },
    ],
    totals: {
      currency: "USD",
      subtotal_cents: 120000,
      shipping_cents: 3400,
      tax_cents: 0,
      fees_cents: 0,
      total_cents: 123400,
    },
    inspection: { period_hours: 48, starts_on: "DELIVERY_CONFIRMED" },
    delivery: { delivery_days: 7, starts_on: "FUNDING_CONFIRMED" },
    warranty_months: 24,
    returns_days: 30,
    dispute_window_hours: 72,
    evidence_required: ["shipment_manifest", "delivery_confirmation", "invoice"],
    remedies: {
      non_delivery: "cancel_and_refund",
      late_delivery: "cancel_and_refund",
      damaged_goods: "refund_or_replacement",
    },
  },
};

describe("BuyerAgreementCard", () => {
  it("renders the terms-derived product, money breakdown and total", () => {
    render(<BuyerAgreementCard transactionId="vf_1" agreement={agreement} />);

    expect(screen.getByTestId("buyer-agreement-card")).toBeInTheDocument();
    expect(screen.getByText("Nimbus NC-700 ANC Headset")).toBeInTheDocument();
    expect(screen.getByText("NovaTech")).toBeInTheDocument();
    expect(screen.getByText("Pending Buyer")).toHaveClass("mm-buyer-status-pill");
    const money = screen.getByTestId("buyer-agreement-money");
    expect(money).toHaveTextContent("USD 1,200.00");
    expect(money).toHaveTextContent("USD 34.00");
    expect(money).toHaveTextContent("USD 1,234.00");
  });

  it("shows the inspection window and the agreed evidence requirements", () => {
    render(<BuyerAgreementCard transactionId="vf_1" agreement={agreement} />);

    const panel = screen.getByTestId("buyer-agreement-inspection");
    expect(panel).toHaveTextContent("48 hours after delivery confirmed");
    expect(panel).toHaveTextContent("Shipment manifest");
    expect(panel).toHaveTextContent("Delivery confirmation");
    expect(panel).toHaveTextContent("Invoice");
  });

  it("keeps detailed agreement sections collapsed until the buyer opens them", () => {
    render(<BuyerAgreementCard transactionId="vf_1" agreement={agreement} />);

    for (const label of [
      "Seller obligations",
      "Returns and disputes",
      "Agreement acceptance",
      "Agreement digest",
    ]) {
      const section = screen.getByText(label).closest("details") as HTMLDetailsElement;
      expect(section).not.toBeNull();
      expect(section.open).toBe(false);
    }
    const returns = screen.getByText("Returns and disputes").closest("details") as HTMLElement;
    expect(within(returns).getByText("Refund or replacement")).toBeTruthy();
    expect(within(returns).getByText("72 hours")).toBeTruthy();
  });

  it("offers chat-only handoffs and never renders decision buttons", () => {
    render(<BuyerAgreementCard transactionId="vf_1" agreement={agreement} />);

    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.getByRole("link", { name: /review agreement in chat for vf_1/i }),
    ).toHaveAttribute("href", "/chat?transaction_id=vf_1&intent=review");
  });

  it("keeps the raw agreement behind a disclosure", () => {
    render(<BuyerAgreementCard transactionId="vf_1" agreement={agreement} />);

    const raw = screen.getByText("View raw agreement").closest("details") as HTMLElement;
    expect(raw.querySelector("pre")?.textContent).toContain('"agreement_id": "agr_1"');
  });

  it("falls back to top-level agreement fields when nested terms are missing", () => {
    render(
      <BuyerAgreementCard
        transactionId="vf_1"
        agreement={{
          agreement_id: "agr_2",
          agreement_version: 3,
          agreement_hash: HASH,
          amount_cents: 5000,
          currency: "USD",
          status: "AGREED",
          line_items: [{ name: "Fallback item", quantity: 2, attributes: { condition: "new" } }],
        }}
      />,
    );

    expect(screen.getByText("Fallback item")).toBeInTheDocument();
    expect(screen.getByTestId("buyer-agreement-money")).toHaveTextContent("USD 50.00");
    expect(
      within(screen.getByTestId("buyer-agreement-card")).getAllByText("v3").length,
    ).toBeGreaterThan(0);
  });
});
