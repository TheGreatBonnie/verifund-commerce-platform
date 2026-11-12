import type {
  BuyerFulfillmentProjection,
  BuyerInspection,
  BuyerTransactionDetail,
  BuyerTransactionListResponse,
} from "./buyer-transaction-types";

export type ApiError = Error & { status?: number; body?: any };

async function parseOrThrow<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const message =
      body?.error?.message || body?.detail || body?.message || `Request failed (${res.status})`;
    const err = new Error(typeof message === "string" ? message : JSON.stringify(message)) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body as T;
}

export async function listBuyerTransactions(
  params: Record<string, string | number | undefined> = {},
): Promise<BuyerTransactionListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const res = await fetch(`/api/buyer/transactions${qs.size ? `?${qs.toString()}` : ""}`, {
    cache: "no-store",
  });
  return parseOrThrow<BuyerTransactionListResponse>(res);
}

export async function getBuyerTransaction(transactionId: string): Promise<BuyerTransactionDetail> {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}`, {
    cache: "no-store",
  });
  return parseOrThrow<BuyerTransactionDetail>(res);
}

export async function getBuyerFulfillment(transactionId: string): Promise<BuyerFulfillmentProjection> {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/fulfillment`, {
    cache: "no-store",
  });
  return parseOrThrow<BuyerFulfillmentProjection>(res);
}

export async function getBuyerInspection(transactionId: string): Promise<BuyerInspection> {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/inspection`, {
    cache: "no-store",
  });
  return parseOrThrow<BuyerInspection>(res);
}

export async function submitBuyerEvidence(transactionId: string, formData: FormData) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/evidence`, {
    method: "POST",
    body: formData,
  });
  return parseOrThrow<any>(res);
}

export async function openBuyerDispute(
  transactionId: string,
  payload: {
    claim_type?: string;
    reason_code?: string;
    claim?: string;
    requirement_ids?: string[];
    evidence_refs?: string[];
  },
) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/dispute`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseOrThrow<any>(res);
}

export async function acceptBuyerTransaction(transactionId: string) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/accept`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  return parseOrThrow<any>(res);
}

export async function confirmBuyerDelivery(
  transactionId: string,
  payload: Record<string, any> = {},
) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/delivery-confirmed`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseOrThrow<any>(res);
}
