import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createOrderActionMock,
  captureOrderActionMock,
  pollFundingActionMock,
  buttonProps,
} = vi.hoisted(() => ({
  createOrderActionMock: vi.fn(),
  captureOrderActionMock: vi.fn(),
  pollFundingActionMock: vi.fn(),
  buttonProps: { current: null as any },
}));

vi.mock("@/app/actions", () => ({
  createOrderAction: createOrderActionMock,
  captureOrderAction: captureOrderActionMock,
  pollFundingAction: pollFundingActionMock,
}));

vi.mock("@paypal/react-paypal-js/sdk-v6", () => ({
  PayPalProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="paypal-provider">{children}</div>
  ),
  PayPalOneTimePaymentButton: (props: any) => {
    buttonProps.current = props;
    return (
      <button
        type="button"
        data-testid="paypal-button"
        disabled={props.disabled}
        onClick={async () => {
          try {
            await props.createOrder?.();
            await props.onApprove?.({ orderId: "ORDER-1" });
          } catch {
            props.onError?.(new Error("failed"));
          }
        }}
      >
        Pay with PayPal
      </button>
    );
  },
}));

import { PayPalCheckoutCard } from "@/features/chat/verifund-tools";

const ARGS = {
  transaction_id: "vf_1",
  amount_cents: 340000,
  currency: "USD",
  agreement: {
    agreement_id: "agr_1",
    agreement_version: 1,
    terms: {
      parties: { seller: { display_name: "NovaTech" } },
      items: [
        {
          sku: "NC-700",
          name: "Nimbus NC-700 ANC Headset",
          quantity: 12,
          unit_price_cents: 28050,
          warranty_addon_cents: 0,
          attributes: { image_url: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500", condition: "new" },
        },
      ],
      totals: {
        currency: "USD",
        subtotal_cents: 336600,
        shipping_cents: 3400,
        tax_cents: 0,
        fees_cents: 0,
        total_cents: 340000,
      },
      inspection: { period_hours: 48 },
    },
  },
  expires_at: "2026-10-28T12:00:00Z",
  message: "Complete the PayPal checkout to fund this transaction.",
};

function setup(overrides: Partial<typeof ARGS> = {}, pollIntervalMs = 0) {
  const respond = vi.fn().mockResolvedValue(undefined);
  const onVerifundAction = vi.fn();
  render(
    <PayPalCheckoutCard
      args={{ ...ARGS, ...overrides }}
      respond={respond}
      onVerifundAction={onVerifundAction}
      pollIntervalMs={pollIntervalMs}
    />,
  );
  return { respond, onVerifundAction };
}

describe("PayPalCheckoutCard", () => {
  beforeEach(() => {
    createOrderActionMock.mockReset();
    captureOrderActionMock.mockReset();
    pollFundingActionMock.mockReset();
    buttonProps.current = null;
  });

  it("renders the server-authoritative amount", () => {
    setup();
    expect(screen.getByTestId("paypal-checkout")).toBeTruthy();
    expect(screen.getByText("Secure payment")).toBeTruthy();
    expect(screen.getByText(/\$3,400\.00/)).toBeTruthy();
    expect(screen.getByText(/USD/)).toBeTruthy();
  });

  it("renders the agreement-derived product and the charged amount", () => {
    setup();
    expect(screen.getByTestId("checkout-product-summary")).toHaveTextContent(
      "Nimbus NC-700 ANC Headset",
    );
    expect(screen.getByTestId("checkout-order-summary")).toHaveTextContent(
      "Fees",
    );
    expect(screen.getByTestId("verifund-checkout-amount")).toHaveTextContent(
      "$3,400.00",
    );
  });

  it("shows fees when the agreement includes them", () => {
    setup({
      agreement: {
        ...ARGS.agreement,
        terms: {
          ...ARGS.agreement.terms,
          items: [
            {
              ...ARGS.agreement.terms.items[0],
              unit_price_cents: 25000,
            },
          ],
          totals: {
            ...ARGS.agreement.terms.totals,
            subtotal_cents: 300000,
            fees_cents: 36600,
            total_cents: 340000,
          },
        },
      },
    });
    const summary = screen.getByTestId("checkout-order-summary");
    expect(summary).toHaveTextContent("$3,000.00");
    expect(summary).toHaveTextContent("$366.00");
    expect(screen.queryByTestId("checkout-amount-mismatch")).toBeNull();
  });

  it("flags a divergence between the agreement total and the charge", () => {
    setup({
      agreement: {
        ...ARGS.agreement,
        terms: {
          ...ARGS.agreement.terms,
          totals: {
            ...ARGS.agreement.terms.totals,
            total_cents: 340100,
          },
        },
      },
    });
    expect(screen.getByTestId("checkout-amount-mismatch")).toHaveTextContent(
      "$3,401.00",
    );
    expect(screen.getByTestId("verifund-checkout-amount")).toHaveTextContent(
      "$3,400.00",
    );
  });

  it("creates the order through the server action", async () => {
    createOrderActionMock.mockResolvedValue({ id: "ORDER-1" });
    setup();

    await waitFor(() => expect(buttonProps.current).not.toBeNull());
    await expect(buttonProps.current.createOrder()).resolves.toEqual({
      orderId: "ORDER-1",
    });
    expect(createOrderActionMock).toHaveBeenCalledWith({
      transactionId: "vf_1",
    });
  });

  it("responds completed with the settled projection", async () => {
    createOrderActionMock.mockResolvedValue({ id: "ORDER-1" });
    captureOrderActionMock.mockResolvedValue({
      orderId: "ORDER-1",
      captureId: "CAP-1",
      status: "COMPLETED",
      amountCents: 340000,
      currency: "USD",
      settlementState: "FUNDED",
    });
    const { respond } = setup();

    fireEvent.click(screen.getByTestId("paypal-button"));

    await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
    expect(respond.mock.calls[0][0]).toMatchObject({
      status: "completed",
      transaction_id: "vf_1",
      order_id: "ORDER-1",
      capture_id: "CAP-1",
      projection: { transaction_id: "vf_1", state: "FUNDED" },
    });
    expect(pollFundingActionMock).not.toHaveBeenCalled();
  });

  it("polls while the capture is pending before responding", async () => {
    createOrderActionMock.mockResolvedValue({ id: "ORDER-1" });
    captureOrderActionMock.mockResolvedValue({
      orderId: "ORDER-1",
      captureId: "CAP-1",
      status: "PENDING",
      amountCents: 340000,
      currency: "USD",
      settlementState: "FUNDING_PENDING",
    });
    pollFundingActionMock.mockResolvedValue({ state: "FUNDED" });
    const { respond } = setup();

    fireEvent.click(screen.getByTestId("paypal-button"));

    expect(await screen.findByText(/confirming payment/i)).toBeTruthy();
    await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
    expect(pollFundingActionMock).toHaveBeenCalledWith({
      transactionId: "vf_1",
    });
    expect(respond.mock.calls[0][0].projection.state).toBe("FUNDED");
  });

  it("responds canceled when the buyer closes the popup", async () => {
    const { respond } = setup();
    await waitFor(() => expect(buttonProps.current).not.toBeNull());

    buttonProps.current.onCancel();

    await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
    expect(respond.mock.calls[0][0]).toMatchObject({
      status: "canceled",
      transaction_id: "vf_1",
    });
  });

  it("offers the redirect fallback when the SDK errors", async () => {
    const { respond } = setup();
    await waitFor(() => expect(buttonProps.current).not.toBeNull());

    buttonProps.current.onError(new Error("sdk failed"));

    expect(await screen.findByText(/paypal is unavailable/i)).toBeTruthy();
    expect(screen.getByText("PayPal unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /pay on paypal/i }));

    await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
    expect(respond.mock.calls[0][0]).toMatchObject({
      status: "fallback",
      transaction_id: "vf_1",
    });
  });

  it("reports a failed capture without claiming success", async () => {
    createOrderActionMock.mockResolvedValue({ id: "ORDER-1" });
    captureOrderActionMock.mockRejectedValue(new Error("capture failed"));
    setup();

    fireEvent.click(screen.getByTestId("paypal-button"));

    expect(await screen.findByText("capture failed")).toBeTruthy();
    expect(screen.getByText("Payment not completed")).toBeTruthy();
  });

  it("disables the button while a request is in flight", async () => {
    createOrderActionMock.mockResolvedValue({ id: "ORDER-1" });
    captureOrderActionMock.mockResolvedValue({
      orderId: "ORDER-1",
      captureId: "CAP-1",
      status: "PENDING",
      amountCents: 340000,
      currency: "USD",
      settlementState: "FUNDING_PENDING",
    });
    pollFundingActionMock.mockImplementation(() => new Promise(() => {}));
    setup(undefined, 0);

    fireEvent.click(screen.getByTestId("paypal-button"));

    await waitFor(() =>
      expect(screen.getByTestId("paypal-button")).toHaveProperty(
        "disabled",
        true,
      ),
    );
  });
});
