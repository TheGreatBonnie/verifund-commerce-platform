import { beforeEach, describe, expect, it, vi } from "vitest";

const { createOrderMock, captureOrderMock } = vi.hoisted(() => ({
  createOrderMock: vi.fn(),
  captureOrderMock: vi.fn(),
}));

vi.mock("@paypal/paypal-server-sdk", () => ({
  Client: vi.fn(() => ({})),
  Environment: { Production: "production", Sandbox: "sandbox" },
  OrdersController: vi.fn(() => ({
    createOrder: createOrderMock,
    captureOrder: captureOrderMock,
  })),
  CheckoutPaymentIntent: { Capture: "CAPTURE" },
}));

import { capturePayPalOrder, createPayPalOrder } from "@/lib/paypal";

describe("paypal server helpers", () => {
  beforeEach(() => {
    createOrderMock.mockReset();
    captureOrderMock.mockReset();
  });

  it("creates an order for the server-authoritative amount", async () => {
    createOrderMock.mockResolvedValue({ result: { id: "ORDER-1" } });

    const id = await createPayPalOrder("3400.00", "USD", "fund:vf_1:embedded:v1");

    expect(id).toBe("ORDER-1");
    expect(createOrderMock).toHaveBeenCalledWith({
      body: {
        intent: "CAPTURE",
        purchaseUnits: [
          { amount: { currencyCode: "USD", value: "3400.00" } },
        ],
      },
      paypalRequestId: "fund:vf_1:embedded:v1",
    });
  });

  it("rejects an order response without an id", async () => {
    createOrderMock.mockResolvedValue({ result: {} });

    await expect(
      createPayPalOrder("3400.00", "USD", "fund:vf_1:embedded:v1"),
    ).rejects.toThrow("missing order ID");
  });

  it("captures an order and normalizes the amount to cents", async () => {
    captureOrderMock.mockResolvedValue({
      result: {
        purchaseUnits: [
          {
            payments: {
              captures: [
                {
                  id: "CAP-1",
                  status: "COMPLETED",
                  amount: { value: "3400.00", currencyCode: "USD" },
                },
              ],
            },
          },
        ],
      },
    });

    const capture = await capturePayPalOrder("ORDER-1", "capture:vf_1:v1");

    expect(capture).toEqual({
      captureId: "CAP-1",
      status: "COMPLETED",
      amountCents: 340000,
      currency: "USD",
    });
    expect(captureOrderMock).toHaveBeenCalledWith({
      id: "ORDER-1",
      paypalRequestId: "capture:vf_1:v1",
    });
  });

  it("rejects a capture response without a capture id", async () => {
    captureOrderMock.mockResolvedValue({ result: { purchaseUnits: [] } });

    await expect(
      capturePayPalOrder("ORDER-1", "capture:vf_1:v1"),
    ).rejects.toThrow("missing capture ID");
  });
});
