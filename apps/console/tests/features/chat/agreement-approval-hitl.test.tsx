import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgreementApprovalHitlCard } from "@/features/chat/verifund-tools";

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
      warranty_addon_cents: 0,
      attributes: {
        color: "#eef2ed",
        color_name: "black",
        image_emoji: "🎧",
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
        warranty_addon_cents: 0,
        attributes: { image_emoji: "🎧", condition: "new" },
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

const args = {
  agreement,
  version: 1,
  digest: HASH,
  seller_decision: { status: "accepted" },
  precheck: { recommendation: "pass" },
  review_url: "/agreements/agr_1",
};

describe("AgreementApprovalHitlCard", () => {
  it("renders the product summary and the terms-derived total", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    expect(screen.getByTestId("agreement-approval-hitl")).toBeInTheDocument();
    expect(
      screen.getByTestId("agreement-product-summary"),
    ).toHaveTextContent("Nimbus NC-700 ANC Headset");
    expect(screen.getByTestId("agreement-money-rows")).toHaveTextContent(
      "$1,234.00",
    );
  });

  it("renders the inspection window and the agreed evidence", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    const panel = screen.getByTestId("agreement-inspection-panel");
    expect(panel).toHaveTextContent("48 hours");
    expect(panel).toHaveTextContent("Delivery confirmation");
  });

  it("renders the agreement's remedy rather than demo copy", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    const returns = screen
      .getByText("Returns and disputes")
      .closest("details") as HTMLDetailsElement;
    expect(returns.open).toBe(false);
    expect(within(returns).getByText("Refund or replacement")).toBeTruthy();
    expect(within(returns).getByText("72 hours")).toBeTruthy();
  });
});
