import {
  CheckoutPaymentIntent,
  Client,
  Environment,
  OrdersController,
} from "@paypal/paypal-server-sdk";

let controller: OrdersController | null = null;

function ordersController(): OrdersController {
  if (!controller) {
    const client = new Client({
      clientCredentialsAuthCredentials: {
        oAuthClientId: process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? "",
        oAuthClientSecret: process.env.PAYPAL_CLIENT_SECRET ?? "",
      },
      environment:
        process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT === "production"
          ? Environment.Production
          : Environment.Sandbox,
    });
    controller = new OrdersController(client);
  }
  return controller;
}

export async function createPayPalOrder(
  amount: string,
  currency: string,
  idempotencyKey: string,
): Promise<string> {
  const { result } = await ordersController().createOrder({
    body: {
      intent: CheckoutPaymentIntent.Capture,
      purchaseUnits: [{ amount: { currencyCode: currency, value: amount } }],
    },
    paypalRequestId: idempotencyKey,
  });
  if (!result.id) {
    throw new Error("PayPal order creation failed: missing order ID");
  }
  return result.id;
}

export type PayPalCapture = {
  captureId: string;
  status: string;
  amountCents: number;
  currency: string;
};

export async function capturePayPalOrder(
  orderId: string,
  idempotencyKey: string,
): Promise<PayPalCapture> {
  const { result } = await ordersController().captureOrder({
    id: orderId,
    paypalRequestId: idempotencyKey,
  });
  const capture = (result as any).purchaseUnits?.[0]?.payments?.captures?.[0];
  if (!capture?.id) {
    throw new Error("PayPal capture failed: missing capture ID");
  }
  return {
    captureId: capture.id as string,
    status: capture.status as string,
    amountCents: Math.round(Number(capture.amount.value) * 100),
    currency: capture.amount.currencyCode as string,
  };
}
