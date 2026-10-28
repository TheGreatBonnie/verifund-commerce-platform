import type {
  RegistrySeller,
  SellerDashboard,
  MarketplaceProduct,
  TraceEvent,
  Mandate,
  Award,
  Order,
  CancelReasonCode,
  SettlementProjection,
  SettlementReceipt,
  SettlementResponse,
  SettlementReviewReason,
} from "./types";

export async function fetchTrace(
  runId: string,
  afterSeq = 0,
): Promise<TraceEvent[]> {
  const response = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/trace?after_seq=${afterSeq}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Trace request failed (${response.status})`);
  }
  return (await response.json()) as TraceEvent[];
}

export async function fetchRegistry(): Promise<RegistrySeller[]> {
  const response = await fetch("/api/registry/sellers", {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Registry request failed (${response.status})`);
  }
  const body = (await response.json()) as { sellers?: RegistrySeller[] };
  return body.sellers ?? [];
}

export async function fetchSellerDashboard(
  sellerId: string,
): Promise<SellerDashboard> {
  const response = await fetch(
    `/api/sellers/${encodeURIComponent(sellerId)}/dashboard`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Seller data request failed (${response.status})`);
  }
  return (await response.json()) as SellerDashboard;
}

export async function fetchMarketplaceProducts(): Promise<MarketplaceProduct[]> {
  const response = await fetch("/api/marketplace/products", { cache: "no-store" });
  if (!response.ok) throw new Error(`Marketplace request failed (${response.status})`);
  const body = (await response.json()) as { products?: MarketplaceProduct[] };
  return body.products ?? [];
}

export type BuyerRun = {
  run_id: string;
  stage?: string;
  mandate?: Mandate | null;
  award?: Award | null;
  order?: Order | null;
  settlement?: SettlementProjection | null;
  error?: { code?: string; message?: string } | string | null;
  created_at?: string;
  updated_at?: string;
};

export async function fetchRuns(limit = 50): Promise<BuyerRun[]> {
  const response = await fetch(`/api/runs?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Runs request failed (${response.status})`);
  }
  return (await response.json()) as BuyerRun[];
}

export async function fetchRun(runId: string): Promise<BuyerRun> {
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Run request failed (${response.status})`);
  }
  return (await response.json()) as BuyerRun;
}


async function settlementJson<T>(
  runId: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/settlement${path}`,
    {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    },
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Settlement request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function fetchSettlement(runId: string) {
  return settlementJson<SettlementProjection>(runId, "");
}

export function advanceSettlement(runId: string) {
  return settlementJson<SettlementResponse>(runId, "/advance", {
    method: "POST",
    body: JSON.stringify({ action: "refresh" }),
  });
}

export function releaseSettlement(
  runId: string,
  body: { released_by: string; note?: string; override?: boolean },
) {
  return settlementJson<SettlementResponse>(runId, "/release", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function reviewSettlement(
  runId: string,
  body: {
    action: "flag_review" | "retry_payout";
    reason?: SettlementReviewReason;
    note?: string;
  },
) {
  return settlementJson<SettlementResponse>(runId, "/review", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cancelSettlement(
  runId: string,
  body: { reason_code: CancelReasonCode; note?: string },
) {
  return settlementJson<SettlementResponse>(runId, "/cancel", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchSettlementReceipt(runId: string) {
  return settlementJson<SettlementReceipt>(runId, "/receipt");
}

export function settlementEvidenceUrl(
  runId: string,
  evidenceId: string,
): string {
  return `/api/runs/${encodeURIComponent(runId)}/settlement/evidence/${encodeURIComponent(evidenceId)}`;
}
