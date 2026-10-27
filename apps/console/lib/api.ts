import type {
  RegistrySeller,
  SellerDashboard,
  MarketplaceProduct,
  TraceEvent,
  Mandate,
  Award,
  Order,
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
