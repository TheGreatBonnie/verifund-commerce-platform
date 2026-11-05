"use server";
import { auth } from "@clerk/nextjs/server";

import { controlPlaneJson } from "@/lib/control-plane-proxy";
import { capturePayPalOrder, createPayPalOrder } from "@/lib/paypal";

type FundingSession = {
  transaction_id: string;
  amount_cents: number;
  currency: string;
  expires_at: string;
  order_attempt: number;
  provider_order_id: string | null;
};

type Projection = {
  state: string;
  funding?: unknown;
};

async function controlPlane<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await controlPlaneJson(path, init);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(
      body?.error ?? `Control plane responded ${response.status}`,
    );
  }
  return body as T;
}

function prepareFunding(transactionId: string) {
  return controlPlane<FundingSession>(
    `/transactions/${transactionId}/funding/prepare`,
    { method: "POST" },
  );
}

function deadlinePassed(expiresAt?: string | null) {
  if (!expiresAt) return false;
  const parsed = Date.parse(expiresAt);
  return Number.isNaN(parsed) || parsed <= Date.now();
}

export async function createOrderAction(input: {
  transactionId: string;
}): Promise<{ id: string }> {
  await auth.protect();
  const session = await prepareFunding(input.transactionId);
  if (
    session.provider_order_id &&
    !deadlinePassed(session.expires_at)
  ) {
    return { id: session.provider_order_id };
  }

  const attempt = (session.order_attempt ?? 0) + 1;
  const orderId = await createPayPalOrder(
    (session.amount_cents / 100).toFixed(2),
    session.currency,
    `fund:${input.transactionId}:embedded:v${attempt}`,
  );
  await controlPlane(`/transactions/${input.transactionId}/funding/attach-order`, {
    method: "POST",
    body: JSON.stringify({ order_id: orderId }),
    headers: { "content-type": "application/json" },
  });
  return { id: orderId };
}

export async function captureOrderAction(input: {
  transactionId: string;
  orderId: string;
}) {
  await auth.protect();
  const session = await prepareFunding(input.transactionId);
  const attempt = Math.max(session.order_attempt ?? 0, 1);
  const capture = await capturePayPalOrder(
    input.orderId,
    `capture:${input.transactionId}:v${attempt}`,
  );
  const projection = await controlPlane<Projection>(
    `/transactions/${input.transactionId}/funding/refresh`,
    { method: "POST" },
  );
  return {
    orderId: input.orderId,
    ...capture,
    settlementState: projection.state,
  };
}

export async function pollFundingAction(input: {
  transactionId: string;
}): Promise<Projection> {
  await auth.protect();
  return controlPlane<Projection>(
    `/transactions/${input.transactionId}/funding/refresh`,
    { method: "POST" },
  );
}
