import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BuyerPaymentCard } from "@/components/buyer/transactions/payment-card";

const captured = {
  status: "captured",
  provider_order_id: "ORDER-123",
  capture_id: "CAP-456",
  capture_status: "COMPLETED",
  capture_amount_cents: 123400,
  capture_currency: "USD",
  completed_at: "2026-11-20T10:30:00Z",
  order_attempt: 1,
};

describe("BuyerPaymentCard", () => {
  it("renders the captured amount, status and payment references", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={captured}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    expect(screen.getByTestId("buyer-payment-card")).toBeInTheDocument();
    expect(screen.getByText("Captured")).toHaveClass(
      "mm-buyer-status-pill",
      "is-signal",
    );
    expect(screen.getByTestId("buyer-payment-money")).toHaveTextContent(
      "USD 1,234.00",
    );
    expect(screen.getByTestId("buyer-payment-money")).toHaveTextContent(
      "Agreed amount",
    );
    const references = screen.getByTestId("buyer-payment-references");
    expect(references).toHaveTextContent("ORDER-123");
    expect(references).toHaveTextContent("CAP-456");
    expect(references).toHaveTextContent("COMPLETED");
  });

  it("offers the pending checkout link without claiming capture", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={{
          status: "pending",
          payer_action_url: "https://www.paypal.com/checkout?token=abc",
          order_attempt: 2,
        }}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    expect(screen.getByTestId("buyer-payment-pending")).toHaveTextContent(
      "Payment not yet captured",
    );
    expect(screen.getByTestId("buyer-payment-money")).toHaveTextContent(
      "Not captured",
    );
    const checkout = screen.getByRole("link", { name: /continue checkout/i });
    expect(checkout).toHaveAttribute(
      "href",
      "https://www.paypal.com/checkout?token=abc",
    );
    expect(checkout).toHaveAttribute("target", "_blank");
    expect(checkout).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("surfaces a failed payment error in an alert", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={{
          status: "create_failed",
          last_error: "PayPal order creation failed",
        }}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "PayPal order creation failed",
    );
    expect(screen.queryByTestId("buyer-payment-pending")).toBeNull();
  });

  it("flags a mismatch between the agreed and captured amounts", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={{
          status: "captured",
          capture_amount_cents: 99900,
          capture_currency: "EUR",
        }}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    const warning = screen.getByTestId("buyer-payment-mismatch");
    expect(warning).toHaveClass("mm-amount-warning");
    expect(warning).toHaveTextContent("USD 1,234.00");
    expect(warning).toHaveTextContent("EUR 999.00");
  });

  it("makes a refund explicit without implying a new payment", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={{ status: "refunded", capture_status: "REFUNDED" }}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    expect(screen.getByTestId("buyer-payment-reversal")).toHaveTextContent(
      "refunded",
    );
  });

  it("keeps payment authority in chat and the raw record disclosed", () => {
    render(
      <BuyerPaymentCard
        transactionId="vf_1"
        payment={captured}
        agreedAmountCents={123400}
        currency="USD"
      />,
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.getByRole("link", { name: /review payment in chat for vf_1/i }),
    ).toHaveAttribute("href", "/chat?transaction_id=vf_1&intent=review");
    const raw = screen
      .getByText("View raw payment")
      .closest("details") as HTMLElement;
    expect(raw.querySelector("pre")?.textContent).toContain(
      '"provider_order_id": "ORDER-123"',
    );
  });

  it("renders an honest record when the funding projection is empty", () => {
    render(<BuyerPaymentCard transactionId="vf_1" payment={{}} />);

    expect(screen.getByTestId("buyer-payment-references")).toHaveTextContent(
      "Not recorded",
    );
    expect(screen.queryByTestId("buyer-payment-pending")).toBeNull();
    expect(screen.queryByTestId("buyer-payment-mismatch")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
