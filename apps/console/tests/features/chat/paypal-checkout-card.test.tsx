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
    expect(screen.getByText(/\$3,400\.00/)).toBeTruthy();
    expect(screen.getByText(/USD/)).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: /pay on paypal/i }));

    await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
    expect(respond.mock.calls[0][0]).toMatchObject({
      status: "fallback",
      transaction_id: "vf_1",
    });
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
