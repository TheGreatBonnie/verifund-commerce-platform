import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  controlPlaneJsonMock,
  createPayPalOrderMock,
  capturePayPalOrderMock,
  protectMock,
} = vi.hoisted(() => ({
  controlPlaneJsonMock: vi.fn(),
  createPayPalOrderMock: vi.fn(),
  capturePayPalOrderMock: vi.fn(),
  protectMock: vi.fn(),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect: protectMock }),
}));

vi.mock("@/lib/control-plane-proxy", () => ({
  controlPlaneJson: controlPlaneJsonMock,
}));

vi.mock("@/lib/paypal", () => ({
  createPayPalOrder: createPayPalOrderMock,
  capturePayPalOrder: capturePayPalOrderMock,
}));

import {
  captureOrderAction,
  createOrderAction,
  pollFundingAction,
} from "@/app/actions";

const SESSION = {
  transaction_id: "vf_1",
  amount_cents: 340000,
  currency: "USD",
  expires_at: "2999-01-01T00:00:00Z",
  order_attempt: 0,
  provider_order_id: null,
};

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function routes(prepare: unknown = SESSION) {
  controlPlaneJsonMock.mockImplementation((path: string) => {
    if (path.endsWith("/funding/prepare")) return Promise.resolve(respond(prepare));
    if (path.endsWith("/funding/attach-order")) {
      return Promise.resolve(respond({ state: "FUNDING_PENDING" }));
    }
    if (path.endsWith("/funding/refresh")) {
      return Promise.resolve(respond({ state: "FUNDED", funding: null }));
    }
    return Promise.resolve(respond({ error: "unexpected path" }, 500));
  });
}

describe("checkout server actions", () => {
  beforeEach(() => {
    controlPlaneJsonMock.mockClear();
    createPayPalOrderMock.mockClear();
    capturePayPalOrderMock.mockClear();
    protectMock.mockResolvedValue({ userId: "user_1" });
  });

  it("prepares, creates, and attaches the order before returning it", async () => {
    routes();
    createPayPalOrderMock.mockResolvedValue("ORDER-1");

    const result = await createOrderAction({ transactionId: "vf_1" });

    expect(result).toEqual({ id: "ORDER-1" });
    const paths = controlPlaneJsonMock.mock.calls.map((call) => call[0]);
    expect(paths).toEqual([
      "/transactions/vf_1/funding/prepare",
      "/transactions/vf_1/funding/attach-order",
    ]);
    expect(createPayPalOrderMock).toHaveBeenCalledWith(
      "3400.00",
      "USD",
      "fund:vf_1:embedded:v1",
    );
    const attachInit = controlPlaneJsonMock.mock.calls[1][1];
    expect(JSON.parse(attachInit.body)).toEqual({ order_id: "ORDER-1" });
  });

  it("ignores a browser-supplied amount", async () => {
    routes();
    createPayPalOrderMock.mockResolvedValue("ORDER-1");

    await createOrderAction({
      transactionId: "vf_1",
      // @ts-expect-error the action must never accept an amount
      amountCents: 1,
    });

    expect(createPayPalOrderMock).toHaveBeenCalledWith(
      "3400.00",
      "USD",
      expect.any(String),
    );
  });

  it("reuses an attached order while the deadline is live", async () => {
    routes({ ...SESSION, order_attempt: 1, provider_order_id: "ORDER-9" });

    const result = await createOrderAction({ transactionId: "vf_1" });

    expect(result).toEqual({ id: "ORDER-9" });
    expect(createPayPalOrderMock).not.toHaveBeenCalled();
    expect(controlPlaneJsonMock).toHaveBeenCalledTimes(1);
  });

  it("creates a new attempt after the deadline", async () => {
    routes({
      ...SESSION,
      order_attempt: 1,
      provider_order_id: "ORDER-9",
      expires_at: "2000-01-01T00:00:00Z",
    });
    createPayPalOrderMock.mockResolvedValue("ORDER-10");

    const result = await createOrderAction({ transactionId: "vf_1" });

    expect(result).toEqual({ id: "ORDER-10" });
    expect(createPayPalOrderMock).toHaveBeenCalledWith(
      "3400.00",
      "USD",
      "fund:vf_1:embedded:v2",
    );
  });

  it("throws the control plane error instead of returning it", async () => {
    controlPlaneJsonMock.mockResolvedValue(
      respond({ error: "conflict", code: "conflict" }, 409),
    );

    await expect(createOrderAction({ transactionId: "vf_1" })).rejects.toThrow(
      "conflict",
    );
    expect(createPayPalOrderMock).not.toHaveBeenCalled();
  });

  it("captures with the attached attempt and refreshes the projection", async () => {
    routes({ ...SESSION, order_attempt: 2 });
    capturePayPalOrderMock.mockResolvedValue({
      captureId: "CAP-1",
      status: "COMPLETED",
      amountCents: 340000,
      currency: "USD",
    });

    const result = await captureOrderAction({
      transactionId: "vf_1",
      orderId: "ORDER-1",
    });

    expect(capturePayPalOrderMock).toHaveBeenCalledWith(
      "ORDER-1",
      "capture:vf_1:v2",
    );
    expect(result).toMatchObject({
      orderId: "ORDER-1",
      captureId: "CAP-1",
      settlementState: "FUNDED",
    });
  });

  it("polls the funding projection", async () => {
    routes();

    const result = await pollFundingAction({ transactionId: "vf_1" });

    expect(result.state).toBe("FUNDED");
    expect(controlPlaneJsonMock).toHaveBeenCalledWith(
      "/transactions/vf_1/funding/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
